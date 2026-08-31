"""Conservative screenshot-based WCAG contrast measurements for mobile elements."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from io import BytesIO
from typing import Any

from PIL import Image

_BOUNDS_PATTERN = re.compile(r"\[(\d+),(\d+)]\[(\d+),(\d+)]")
_TEXT_FIELDS = ("text", "hint")
_CONTROL_CLASS_TOKENS = (
    "button",
    "checkbox",
    "switch",
    "radio",
    "seekbar",
    "slider",
    "edittext",
    "textfield",
    "spinner",
    "tab",
)
_GRAPHIC_CLASS_TOKENS = ("image", "icon")
_BACKGROUND_MINIMUM_SHARE = 0.55
_FOREGROUND_MINIMUM_SHARE = 0.002
_MINIMUM_FOREGROUND_PIXELS = 8
_QUANTIZATION_STEP = 16


def calculate_contrast_measurements(
    screenshot_bytes: bytes,
    elements: Sequence[object],
) -> list[dict[str, object]]:
    """Return reliable foreground/background contrast candidates for visible elements."""
    image = Image.open(BytesIO(screenshot_bytes)).convert("RGB")
    element_data = [element for element in elements if isinstance(element, Mapping)]
    bounds_by_element = [_parse_bounds(element.get("bounds")) for element in element_data]
    scale_x, scale_y = _screen_scale(image.size, bounds_by_element)
    return [
        measurement
        for element, bounds in zip(element_data, bounds_by_element, strict=True)
        if (measurement := _measure_element(image, element, bounds, scale_x, scale_y)) is not None
    ]


def _measure_element(
    image: Image.Image,
    element: Mapping[str, object],
    bounds: Bounds | None,
    scale_x: float,
    scale_y: float,
) -> dict[str, object] | None:
    candidate_type = _candidate_type(element)
    if candidate_type is None or not _is_eligible(element) or bounds is None:
        return None
    scaled_bounds = _scaled_bounds(bounds, image.size, scale_x, scale_y)
    if scaled_bounds is None:
        return None
    foreground, background = _sample_colors(image.crop(scaled_bounds))
    if foreground is None or background is None:
        return None
    return {
        "element_index": element.get("index"),
        "bounds": element.get("bounds"),
        "candidate_type": candidate_type,
        "allowed_rule": _allowed_rule(candidate_type),
        "contrast_ratio": round(_contrast_ratio(foreground, background), 2),
        "foreground_color": _hex_color(foreground),
        "background_color": _hex_color(background),
        "threshold": _threshold(element, candidate_type),
        "measurable": True,
    }


def _candidate_type(element: Mapping[str, object]) -> str | None:
    if any(_has_text(element.get(field)) for field in _TEXT_FIELDS):
        return "text"
    class_name = str(element.get("class_name") or "").casefold()
    if (
        bool(element.get("clickable"))
        or bool(element.get("focusable"))
        or any(token in class_name for token in _CONTROL_CLASS_TOKENS)
    ):
        return "ui_component"
    if any(token in class_name for token in _GRAPHIC_CLASS_TOKENS):
        return "image"
    return None


def _is_eligible(element: Mapping[str, object]) -> bool:
    importance = str(element.get("important_for_accessibility") or "").strip().casefold()
    return bool(element.get("enabled", True)) and importance != "no"


def _parse_bounds(value: object) -> Bounds | None:
    if not isinstance(value, str):
        return None
    match = _BOUNDS_PATTERN.fullmatch(value.strip())
    if match is None:
        return None
    left, top, right, bottom = map(int, match.groups())
    return (left, top, right, bottom) if left < right and top < bottom else None


def _screen_scale(image_size: tuple[int, int], bounds: Sequence[Bounds | None]) -> tuple[float, float]:
    valid_bounds = [bound for bound in bounds if bound is not None]
    if not valid_bounds:
        return (1.0, 1.0)
    max_right = max(bound[2] for bound in valid_bounds)
    max_bottom = max(bound[3] for bound in valid_bounds)
    width, height = image_size
    return (width / max_right if max_right > width else 1.0, height / max_bottom if max_bottom > height else 1.0)


def _scaled_bounds(
    bounds: Bounds,
    image_size: tuple[int, int],
    scale_x: float,
    scale_y: float,
) -> Bounds | None:
    width, height = image_size
    left, top, right, bottom = (
        round(bounds[0] * scale_x),
        round(bounds[1] * scale_y),
        round(bounds[2] * scale_x),
        round(bounds[3] * scale_y),
    )
    if left < 0 or top < 0 or right > width or bottom > height or left >= right or top >= bottom:
        return None
    return (left, top, right, bottom)


def _sample_colors(crop: Image.Image) -> tuple[Color | None, Color | None]:
    pixels = list(crop.getdata())
    if len(pixels) < _MINIMUM_FOREGROUND_PIXELS:
        return (None, None)
    edge_pixels = _edge_pixels(crop)
    background_bucket, background_count = Counter(_quantize(pixel) for pixel in edge_pixels).most_common(1)[0]
    if background_count / len(edge_pixels) < _BACKGROUND_MINIMUM_SHARE:
        return (None, None)
    background = _average_color(pixel for pixel in pixels if _quantize(pixel) == background_bucket)
    foreground = _foreground_color(pixels, background_bucket)
    return (foreground, background)


def _edge_pixels(crop: Image.Image) -> list[Color]:
    width, height = crop.size
    pixels = crop.load()
    return [
        pixels[x, y]
        for y in range(height)
        for x in range(width)
        if x == 0 or y == 0 or x == width - 1 or y == height - 1
    ]


def _foreground_color(pixels: Sequence[Color], background_bucket: Color) -> Color | None:
    buckets = Counter(_quantize(pixel) for pixel in pixels)
    minimum_count = max(_MINIMUM_FOREGROUND_PIXELS, round(len(pixels) * _FOREGROUND_MINIMUM_SHARE))
    candidates = [
        (bucket, count)
        for bucket, count in buckets.most_common()
        if bucket != background_bucket and count >= minimum_count
    ]
    if not candidates:
        return None
    foreground_bucket, _ = candidates[0]
    return _average_color(pixel for pixel in pixels if _quantize(pixel) == foreground_bucket)


def _quantize(color: Color) -> Color:
    return tuple(channel // _QUANTIZATION_STEP * _QUANTIZATION_STEP for channel in color)


def _average_color(colors: Any) -> Color:
    values = list(colors)
    return tuple(round(sum(color[index] for color in values) / len(values)) for index in range(3))


def _contrast_ratio(foreground: Color, background: Color) -> float:
    lighter, darker = sorted((_relative_luminance(foreground), _relative_luminance(background)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _relative_luminance(color: Color) -> float:
    channels = [channel / 255 for channel in color]
    linear = [
        channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4 for channel in channels
    ]
    return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2]


def _allowed_rule(candidate_type: str) -> str:
    if candidate_type == "text":
        return "1.4.3"
    if candidate_type == "image":
        return "1.4.3_or_1.4.11"
    return "1.4.11"


def _threshold(element: Mapping[str, object], candidate_type: str) -> float:
    if candidate_type != "text":
        return 3.0
    font_size = element.get("font_size")
    is_bold = "bold" in str(element.get("font_style") or "").casefold()
    if isinstance(font_size, int | float) and (font_size >= 18 or font_size >= 14 and is_bold):
        return 3.0
    return 4.5


def _has_text(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _hex_color(color: Color) -> str:
    return f"#{color[0]:02X}{color[1]:02X}{color[2]:02X}"


Color = tuple[int, int, int]
Bounds = tuple[int, int, int, int]
