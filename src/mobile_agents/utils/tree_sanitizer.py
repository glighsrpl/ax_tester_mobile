"""Deterministically prune mobile accessibility trees for analysis."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any
from xml.etree import ElementTree

ALLOWED_ATTRIBUTES = frozenset(
    {
        "className",
        "contentDescription",
        "accessibilityLabel",
        "text",
        "hint",
        "clickable",
        "focusable",
        "enabled",
        "checked",
        "resource-id",
        "children",
    }
)
GENERIC_ANDROID_VIEW = "android.view.View"
FLUTTER_NODE_THRESHOLD = 0.8
_BOUNDS_PATTERN = re.compile(r"\[(-?\d+),(-?\d+)]\[(-?\d+),(-?\d+)]")


def sanitize_tree(raw_tree: dict) -> dict:
    """Return a hierarchy-preserving tree containing only analysis-relevant data."""
    sanitized_nodes = _sanitize_node(raw_tree)
    if len(sanitized_nodes) == 1:
        return sanitized_nodes[0]
    return {"children": sanitized_nodes}


def detect_framework(sanitized_tree: dict) -> str:
    """Classify a sanitized accessibility tree as Flutter or native."""
    nodes = list(_walk_nodes(sanitized_tree))
    if not nodes:
        return "native"

    root_class_name = str(sanitized_tree.get("className") or "")
    if root_class_name == "FlutterView":
        return "flutter"
    if _is_ios_tree(nodes):
        return "flutter" if not any(node.get("accessibilityIdentifier") for node in nodes) else "native"

    generic_view_count = sum(node.get("className") == GENERIC_ANDROID_VIEW for node in nodes)
    has_resource_id = any(node.get("resource-id") for node in nodes)
    return (
        "flutter"
        if generic_view_count / len(nodes) > FLUTTER_NODE_THRESHOLD and not has_resource_id
        else "native"
    )


def xml_tree_to_dict(tree_xml: str) -> dict:
    """Convert an Appium XML tree to the dict representation used by the sanitizer."""
    root = ElementTree.fromstring(tree_xml)
    return _xml_node_to_dict(root)


def _sanitize_node(raw_node: Mapping[str, Any]) -> list[dict[str, Any]]:
    if _is_hidden(raw_node) or _has_zero_size(raw_node.get("bounds")):
        return []

    children = [sanitized_child for child in _children(raw_node) for sanitized_child in _sanitize_node(child)]
    node = {
        key: raw_node[key]
        for key in ALLOWED_ATTRIBUTES - {"children"}
        if key in raw_node and raw_node[key] is not None
    }
    if children:
        node["children"] = children

    if _is_decorative(node):
        return children
    if _is_empty_container(node, children):
        return children
    return [node]


def _children(raw_node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    children = raw_node.get("children", [])
    return [child for child in children if isinstance(child, Mapping)] if isinstance(children, list) else []


def _is_hidden(node: Mapping[str, Any]) -> bool:
    return any(_is_false(node.get(attribute)) for attribute in ("visible", "displayed"))


def _is_false(value: object) -> bool:
    return value is False or isinstance(value, str) and value.strip().casefold() in {"false", "0"}


def _has_zero_size(bounds: object) -> bool:
    if isinstance(bounds, Mapping):
        return _is_zero(bounds.get("width")) or _is_zero(bounds.get("height"))
    if isinstance(bounds, (list, tuple)) and len(bounds) == 4:
        return bounds[2] - bounds[0] == 0 or bounds[3] - bounds[1] == 0
    if not isinstance(bounds, str):
        return False
    match = _BOUNDS_PATTERN.fullmatch(bounds.strip())
    return bool(match and (match.group(1) == match.group(3) or match.group(2) == match.group(4)))


def _is_zero(value: object) -> bool:
    try:
        return float(str(value)) == 0
    except (TypeError, ValueError):
        return False


def _is_decorative(node: Mapping[str, Any]) -> bool:
    return node.get("className") == GENERIC_ANDROID_VIEW and not _has_semantic_attributes(node)


def _is_empty_container(node: Mapping[str, Any], children: list[dict[str, Any]]) -> bool:
    return len(children) == 1 and not _has_semantic_attributes(node)


def _has_semantic_attributes(node: Mapping[str, Any]) -> bool:
    return any(
        node.get(attribute)
        for attribute in (
            "contentDescription",
            "accessibilityLabel",
            "text",
            "hint",
            "resource-id",
            "clickable",
            "focusable",
            "checked",
        )
    )


def _walk_nodes(tree: Mapping[str, Any]):
    yield tree
    for child in _children(tree):
        yield from _walk_nodes(child)


def _is_ios_tree(nodes: list[Mapping[str, Any]]) -> bool:
    return any(str(node.get("className") or "").startswith("XCUIElementType") for node in nodes)


def _xml_node_to_dict(node: ElementTree.Element) -> dict[str, Any]:
    attributes = node.attrib
    tree_node: dict[str, Any] = {
        "className": attributes.get("class") or attributes.get("className") or node.tag,
        "contentDescription": attributes.get("content-desc") or attributes.get("contentDescription"),
        "accessibilityLabel": attributes.get("accessibilityLabel") or attributes.get("label"),
        "text": attributes.get("text") or attributes.get("name"),
        "hint": attributes.get("hint") or attributes.get("hint-text"),
        "clickable": _xml_boolean(attributes.get("clickable")),
        "focusable": _xml_boolean(attributes.get("focusable")),
        "enabled": _xml_boolean(attributes.get("enabled")),
        "checked": _xml_boolean(attributes.get("checked")),
        "resource-id": attributes.get("resource-id") or attributes.get("resourceId"),
        "visible": attributes.get("visible"),
        "displayed": attributes.get("displayed"),
        "bounds": attributes.get("bounds"),
        "children": [_xml_node_to_dict(child) for child in node],
    }
    return {key: value for key, value in tree_node.items() if value not in (None, "", [], False)}


def _xml_boolean(value: str | None) -> bool | None:
    if value is None:
        return None
    return value.strip().casefold() in {"true", "1"}
