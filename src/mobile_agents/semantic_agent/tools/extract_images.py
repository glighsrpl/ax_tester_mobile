"""Extract accessibility-relevant image nodes from mobile UI XML trees."""

from __future__ import annotations

import re
from typing import Any
from xml.etree import ElementTree

MINIMUM_IMAGE_DIMENSION = 10
_ANDROID_IMAGE_CLASSES = {
    "android.widget.ImageButton",
    "android.widget.ImageView",
}
_FLUTTER_IMAGE_IDENTIFIER_PATTERN = re.compile(r"image|icon|img|picture", re.IGNORECASE)
_ANDROID_BOUNDS_PATTERN = re.compile(r"\[(-?\d+),(-?\d+)\]\[(-?\d+),(-?\d+)\]")


def extract_images(tree_xml: str, platform: str = "android") -> list[dict[str, Any]]:
    """Return accessible, meaningfully sized image nodes from a UI tree."""
    if platform == "ios":
        raise NotImplementedError("iOS XCUITest XML support is not implemented yet.")
    if platform != "android":
        raise ValueError(f"Unsupported platform: {platform}")

    root = ElementTree.fromstring(tree_xml)
    images: list[dict[str, Any]] = []
    for node in root.iter():
        if not _is_image_node_android(node) or _is_inaccessible(node):
            continue

        bounds = _parse_android_bounds(node.get("bounds", ""))
        if bounds is None or _is_smaller_than_minimum(bounds):
            continue

        images.append(
            {
                "bounds": bounds,
                "content_description": node.get("content-desc", ""),
                "resource_id": node.get("resource-id", ""),
                "class_name": node.get("class", ""),
                "platform": platform,
            }
        )
    return images


def _is_image_node_android(node: ElementTree.Element) -> bool:
    """Identify Android native and Flutter image representations."""
    class_name = node.get("class", "")
    resource_id = node.get("resource-id", "")
    is_native_image = class_name in _ANDROID_IMAGE_CLASSES or "Image" in class_name
    is_flutter_image = (
        class_name == "android.view.View" and _FLUTTER_IMAGE_IDENTIFIER_PATTERN.search(resource_id) is not None
    )
    return is_native_image or is_flutter_image


def _is_inaccessible(node: ElementTree.Element) -> bool:
    """Return whether a node has explicitly opted out of accessibility."""
    return node.get("importantForAccessibility", "").lower() == "false"


def _parse_android_bounds(bounds_text: str) -> dict[str, int] | None:
    """Parse Android's ``[x1,y1][x2,y2]`` bounds representation."""
    match = _ANDROID_BOUNDS_PATTERN.fullmatch(bounds_text)
    if match is None:
        return None

    x1, y1, x2, y2 = (int(value) for value in match.groups())
    return {"x1": x1, "y1": y1, "x2": x2, "y2": y2}


def _is_smaller_than_minimum(bounds: dict[str, int]) -> bool:
    """Return whether either bounds dimension falls below the image threshold."""
    width = bounds["x2"] - bounds["x1"]
    height = bounds["y2"] - bounds["y1"]
    return width < MINIMUM_IMAGE_DIMENSION or height < MINIMUM_IMAGE_DIMENSION
