"""Crop image regions from mobile screenshots."""

from __future__ import annotations

import base64
from collections.abc import Mapping
from io import BytesIO
from typing import Any

from PIL import Image


def crop_images(
    screenshot: bytes, images_inventory: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return PNG-encoded crops for the valid image regions in an inventory."""
    with Image.open(BytesIO(screenshot)) as screenshot_image:
        screenshot_width, screenshot_height = screenshot_image.size
        crops: list[dict[str, Any]] = []
        for index, image_metadata in enumerate(images_inventory):
            crop_box = _clamp_crop_box(
                image_metadata.get("bounds", {}),
                screenshot_width,
                screenshot_height,
            )
            if crop_box is None:
                continue

            crops.append(
                {
                    "index": index,
                    "image_base64": _encode_png(screenshot_image.crop(crop_box)),
                }
            )
    return crops


def _clamp_crop_box(
    bounds: Mapping[str, Any], screenshot_width: int, screenshot_height: int
) -> tuple[int, int, int, int] | None:
    """Clamp inventory bounds to the screenshot and reject empty regions."""
    try:
        x1 = _clamp(int(bounds["x1"]), screenshot_width)
        y1 = _clamp(int(bounds["y1"]), screenshot_height)
        x2 = _clamp(int(bounds["x2"]), screenshot_width)
        y2 = _clamp(int(bounds["y2"]), screenshot_height)
    except (KeyError, TypeError, ValueError):
        return None

    if x1 >= x2 or y1 >= y2:
        return None
    return x1, y1, x2, y2


def _clamp(coordinate: int, maximum: int) -> int:
    """Constrain a coordinate to an image axis."""
    return max(0, min(coordinate, maximum))


def _encode_png(image: Image.Image) -> str:
    """Encode a PIL image as a base64 PNG string."""
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return base64.b64encode(buffer.getvalue()).decode("ascii")
