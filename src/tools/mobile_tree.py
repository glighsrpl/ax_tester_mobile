import hashlib
import re
from xml.etree import ElementTree

from tools.mobile_base import MobileElementInfo

BOUNDS_RE = re.compile(r"\[(\d+),(\d+)]\[(\d+),(\d+)]")
TRUE_VALUES = {"true", "1"}


def parse_mobile_tree(
    tree_xml: str,
    *,
    page_screenshot: str | None = None,
    screen_id: str | None = None,
) -> list[MobileElementInfo]:
    root = ElementTree.fromstring(tree_xml)
    resolved_screen_id = screen_id or get_screen_id(tree_xml)
    return [
        MobileElementInfo(
            index=index,
            screen_id=resolved_screen_id,
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
            checked=_bool(node, "checked"),
            page_screenshot=page_screenshot,
        )
        for index, node in enumerate(root.iter())
        if node.tag != root.tag
    ]


def get_screen_id(tree_xml: str) -> str:
    try:
        root = ElementTree.fromstring(tree_xml)
    except ElementTree.ParseError:
        return hashlib.sha1(tree_xml.encode("utf-8")).hexdigest()[:12]

    rows = []
    for node in root.iter():
        rows.append(
            "|".join(
                (node.attrib.get(name) or "").strip()
                for name in (
                    "package",
                    "class",
                    "resource-id",
                    "text",
                    "content-desc",
                    "bounds",
                    "clickable",
                    "focusable",
                    "enabled",
                    "scrollable",
                )
            )
        )
    return hashlib.sha1("\n".join(rows).encode("utf-8")).hexdigest()[:12]


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


def _bool(node: ElementTree.Element, name: str, *, default: bool = False) -> bool:
    value = node.attrib.get(name)
    return default if value is None else value.strip().lower() in TRUE_VALUES


def _parse_bounds(bounds: str) -> tuple[int, int, int, int]:
    match = BOUNDS_RE.fullmatch(bounds.strip())
    if not match:
        raise ValueError(f"Invalid mobile bounds: {bounds!r}")
    return tuple(map(int, match.groups()))
