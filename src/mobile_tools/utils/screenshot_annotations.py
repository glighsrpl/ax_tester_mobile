"""Utilities for highlighting mobile accessibility issue bounds in screenshots."""

import re
from collections.abc import Iterable
from io import BytesIO

from PIL import Image, ImageDraw

Bounds = tuple[int, int, int, int]

BOUND_PATTERN = re.compile(r"\[(\d+),(\d+)\]\[(\d+),(\d+)\]")
HIGHLIGHT_COLOR = "red"
HIGHLIGHT_WIDTH = 3


def parse_bounds(html_snippet: object) -> list[Bounds]:
    """Extract valid Android bounds from an issue HTML snippet."""
    if not isinstance(html_snippet, str):
        return []

    return [
        bounds
        for match in BOUND_PATTERN.finditer(html_snippet)
        if _is_valid_bounds(bounds := tuple(map(int, match.groups())))
    ]


def annotate_screenshot(screenshot_bytes: bytes, bounds: Iterable[Bounds]) -> bytes:
    """Return a screenshot with issue bounds outlined in red."""
    parsed_bounds = list(bounds)
    if not parsed_bounds:
        return screenshot_bytes

    try:
        with Image.open(BytesIO(screenshot_bytes)) as screenshot:
            annotated_image = screenshot.copy()
            scaled_bounds = _scale_bounds_to_fit_screenshot(parsed_bounds, annotated_image.width)
            drawing = ImageDraw.Draw(annotated_image)
            for bound in scaled_bounds:
                drawing.rectangle(bound, outline=HIGHLIGHT_COLOR, width=HIGHLIGHT_WIDTH)
            output = BytesIO()
            annotated_image.save(output, format="PNG")
    except (OSError, ValueError):
        return screenshot_bytes

    return output.getvalue()


def _is_valid_bounds(bounds: Bounds) -> bool:
    left, top, right, bottom = bounds
    return left < right and top < bottom


def _scale_bounds_to_fit_screenshot(bounds: list[Bounds], screenshot_width: int) -> list[Bounds]:
    maximum_right = max(right for _, _, right, _ in bounds)
    if maximum_right <= screenshot_width:
        return bounds

    scale = screenshot_width / maximum_right
    return [_scale_bound(bound, scale) for bound in bounds]


def _scale_bound(bounds: Bounds, scale: float) -> Bounds:
    left, top, right, bottom = bounds
    return (
        round(left * scale),
        round(top * scale),
        round(right * scale),
        round(bottom * scale),
    )
