"""
This module provides functions for parsing and processing mobile UI trees represented in XML format.
It includes utilities for extracting information about mobile elements, filtering interactive elements, and compacting the tree representation for easier analysis.
"""

import re
from xml.etree import ElementTree

from mobile_tools.base import MobileElementInfo

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)]\[(\d+),(\d+)]")
TRUE_VALUES = {"true", "1"}
FALSE_VALUES = {"false", "0"}


def parse_mobile_tree(
    tree_xml: str,
    *,
    page_screenshot: str | None = None,
) -> list[MobileElementInfo]:
    root = ElementTree.fromstring(tree_xml)
    nodes = list(root.iter())
    node_indices = {node: index for index, node in enumerate(nodes)}
    parent_indices = {child: node_indices[parent] for parent in nodes for child in parent}
    return [
        MobileElementInfo(
            index=index,
            text=_attr(node, "text"),
            content_desc=_attr(node, "content-desc", "contentDescription", "name", "label"),
            resource_id=_attr(node, "resource-id", "resourceId"),
            class_name=_attr(node, "class", "className", "type"),
            package=_attr(node, "package"),
            bounds=_attr(node, "bounds"),
            clickable=_bool(node, "clickable"),
            focusable=_bool(node, "focusable"),
            enabled=_bool(node, "enabled", default=True),
            selected=_bool(node, "selected"),
            checked=_optional_bool(node, "checked"),
            expanded=_optional_bool(node, "expanded"),
            focused=_bool(node, "focused"),
            page_screenshot=page_screenshot,
            hint=_raw_attr(node, "hint", "hint-text", "hintText", "placeholder"),
            label_for=_attr(node, "labelFor", "label-for", "labeled-by", "labelledBy"),
            input_type=_raw_attr(node, "inputType", "input-type"),
            parent_index=parent_indices.get(node),
            important_for_accessibility=_raw_attr(
                node, "importantForAccessibility", "important-for-accessibility"
            ),
        )
        for index, node in enumerate(nodes)
        if node is not root
    ]


def get_interactive_elements(elements: list[MobileElementInfo]) -> list[MobileElementInfo]:
    return [element for element in elements if element.enabled and element.bounds and element.is_interactive()]


def compact_mobile_tree(elements: list[MobileElementInfo], *, interactive_only: bool = False) -> str:
    rows = get_interactive_elements(elements) if interactive_only else elements
    return "\n".join(_compact_row(element) for element in rows)


def bounds_center(bounds: str) -> tuple[int, int]:
    left, top, right, bottom = _parse_bounds(bounds)
    return (left + right) // 2, (top + bottom) // 2


def bounds_size(bounds: str) -> tuple[int, int]:
    left, top, right, bottom = _parse_bounds(bounds)
    return right - left, bottom - top


def _compact_row(element: MobileElementInfo) -> str:
    label = element.get_label()
    flags = "".join(
        flag
        for flag, enabled in (
            ("C", element.clickable),
            ("F", element.focusable),
            ("E", element.enabled),
            ("S", element.selected),
            ("K", element.checked),
        )
        if enabled
    )
    return (
        f"{element.index}: {element.class_name or '-'}"
        f" id={element.resource_id or '-'}"
        f" label={label or '-'}"
        f" bounds={element.bounds or '-'}"
        f" flags={flags or '-'}"
    )


def _attr(node: ElementTree.Element, *names: str) -> str | None:
    for name in names:
        value = (node.attrib.get(name) or "").strip()
        if value:
            return value
    return None


def _raw_attr(node: ElementTree.Element, *names: str) -> str | None:
    return next((node.attrib[name] for name in names if name in node.attrib), None)


def _bool(node: ElementTree.Element, name: str, *, default: bool = False) -> bool:
    value = node.attrib.get(name)
    return default if value is None else value.strip().lower() in TRUE_VALUES


def _optional_bool(node: ElementTree.Element, name: str) -> bool | None:
    value = node.attrib.get(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    return None


def _parse_bounds(bounds: str) -> tuple[int, int, int, int]:
    match = BOUNDS_RE.fullmatch(bounds.strip())
    if not match:
        raise ValueError(f"Invalid mobile bounds: {bounds!r}")
    return tuple(map(int, match.groups()))
