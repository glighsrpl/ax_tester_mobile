from tools.base import MobileElementInfo
from tools.mobile_screen_scanner import MobileScanSnapshot
from utils.tree_sanitizer import detect_framework, sanitize_tree, xml_tree_to_dict

MAX_STATIC_ELEMENTS = 120
MAX_TEXT_CHARS = 160


def build_static_snapshot_payload(
    snapshot: MobileScanSnapshot,
    snapshot_index: int,
) -> dict[str, object]:
    elements = _relevant_static_elements(snapshot.elements)
    sanitized_tree = sanitize_tree(xml_tree_to_dict(snapshot.tree_xml))
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_index": snapshot_index,
        "activity": snapshot.activity,
        "screenshot": snapshot.screenshot,
        "sanitized_tree": sanitized_tree,
        "framework": detect_framework(sanitized_tree),
        "elements": [_element_payload(element) for element in elements],
    }


def build_static_debug_payload(snapshot_payload: dict[str, object]) -> dict[str, object]:
    elements = snapshot_payload.get("elements")
    return {
        **snapshot_payload,
        "debug": {
            "payload_chars": len(str(snapshot_payload)),
            "element_count": len(elements) if isinstance(elements, list) else 0,
            "has_screenshot": "screenshot" in str(snapshot_payload).lower(),
            "has_tree_xml": "tree_xml" in snapshot_payload,
        },
    }


def build_cross_screen_summary(snapshot: MobileScanSnapshot) -> dict[str, object]:
    """Build the minimal cross-screen input without exposing the accessibility tree."""
    elements = sorted(snapshot.elements, key=lambda element: element.index)
    return {
        "screen_id": snapshot.snapshot_id,
        "activity_name": snapshot.activity.strip() or "unknown",
        "nav_elements": [
            _cross_screen_element(element)
            for element in elements
            if _is_navigation_element(element)
        ],
        "headings": [
            {"level": None, "text": _element_label(element)}
            for element in elements
            if _is_heading(element) and _element_label(element)
        ],
        "focusable_order": [
            _cross_screen_element(element)
            for element in elements
            if element.focusable or element.clickable
        ],
        "labels_map": {
            _element_identifier(element): element.content_desc.strip()
            for element in elements
            if element.content_desc and element.content_desc.strip()
        },
    }


def _cross_screen_element(element: MobileElementInfo) -> dict[str, object]:
    return {
        "identifier": _element_identifier(element),
        "label": _element_label(element),
        "role": _element_role(element),
        "position": element.index,
    }


def _element_identifier(element: MobileElementInfo) -> str:
    return element.resource_id.strip() if element.resource_id else f"index:{element.index}"


def _element_label(element: MobileElementInfo) -> str | None:
    return _trim_text(element.content_desc or element.text or element.hint)


def _element_role(element: MobileElementInfo) -> str:
    class_name = (element.class_name or "").casefold()
    for role, marker in (("button", "button"), ("tab", "tab"), ("image", "image"), ("text input", "edittext")):
        if marker in class_name:
            return role
    return "interactive" if element.is_interactive() else "text"


def _is_navigation_element(element: MobileElementInfo) -> bool:
    searchable = " ".join(
        value.casefold()
        for value in (element.resource_id, element.class_name, element.content_desc, element.text)
        if value
    )
    return any(marker in searchable for marker in ("navigation", "drawer", "tab", "menu", "navigate up"))


def _is_heading(element: MobileElementInfo) -> bool:
    return "heading" in (element.class_name or "").casefold()


def _relevant_static_elements(elements: list[MobileElementInfo]) -> list[MobileElementInfo]:
    return [element for element in elements if _is_static_relevant(element)][:MAX_STATIC_ELEMENTS]


def _is_static_relevant(element: MobileElementInfo) -> bool:
    return bool(
        element.is_interactive()
        or _trim_text(element.text)
        or _trim_text(element.content_desc)
        or _trim_text(element.hint)
        or _trim_text(element.label_for)
        or _is_semantic_class(element)
    )


def _is_semantic_class(element: MobileElementInfo) -> bool:
    class_name = (element.class_name or "").casefold()
    return any(name in class_name for name in ("image", "text", "edit", "button", "checkbox", "switch"))


def _element_payload(element: MobileElementInfo) -> dict[str, object]:
    return {
        "index": element.index,
        "text": _trim_text(element.text),
        "content_desc": _trim_text(element.content_desc),
        "resource_id": _trim_text(element.resource_id),
        "class_name": _trim_text(element.class_name),
        "bounds": _trim_text(element.bounds),
        "clickable": element.clickable,
        "focusable": element.focusable,
        "enabled": element.enabled,
        "selected": element.selected,
        "checked": element.checked,
        "expanded": element.expanded,
        "focused": element.focused,
        "hint": _trim_text(element.hint),
        "label_for": _trim_text(element.label_for),
        "input_type": _trim_text(element.input_type),
        "parent_index": element.parent_index,
        "important_for_accessibility": _trim_text(element.important_for_accessibility),
        "font_size": element.font_size,
        "font_style": _trim_text(element.font_style),
    }


def _trim_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:MAX_TEXT_CHARS] if text else None
