from mobile_tools.base import MobileElementInfo
from mobile_tools.screen_scanner import MobileScanSnapshot

MAX_STATIC_ELEMENTS = 120
MAX_STATIC_TREE_LINES = 120
MAX_TEXT_CHARS = 160


def build_static_snapshot_payload(
    snapshot: MobileScanSnapshot,
    snapshot_index: int,
) -> dict[str, object]:
    elements = _relevant_static_elements(snapshot.elements)
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_index": snapshot_index,
        "activity": snapshot.activity,
        "tree_summary": _limited_tree_summary(elements),
        "elements": [_element_payload(element) for element in elements],
    }


def build_static_debug_payload(snapshot_payload: dict[str, object]) -> dict[str, object]:
    elements = snapshot_payload.get("elements")
    return {
        **snapshot_payload,
        "debug": {
            "payload_chars": len(str(snapshot_payload)),
            "element_count": len(elements) if isinstance(elements, list) else 0,
            "tree_summary_lines": len(str(snapshot_payload.get("tree_summary") or "").splitlines()),
            "has_screenshot": "screenshot" in str(snapshot_payload).lower(),
            "has_tree_xml": "tree_xml" in snapshot_payload,
        },
    }


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


def _limited_tree_summary(elements: list[MobileElementInfo]) -> str:
    return "\n".join(_compact_element_line(element) for element in elements[:MAX_STATIC_TREE_LINES])


def _compact_element_line(element: MobileElementInfo) -> str:
    label = _trim_text(element.get_label()) or "-"
    return (
        f"{element.index}: {element.class_name or '-'}"
        f" id={_trim_text(element.resource_id) or '-'}"
        f" label={label}"
        f" bounds={element.bounds or '-'}"
        f" states={_element_states(element) or '-'}"
    )


def _element_states(element: MobileElementInfo) -> str:
    return ",".join(
        state
        for state, enabled in (
            ("clickable", element.clickable),
            ("focusable", element.focusable),
            ("disabled", not element.enabled),
            ("selected", element.selected),
            ("checked", bool(element.checked)),
            ("expanded", bool(element.expanded)),
            ("focused", element.focused),
        )
        if enabled
    )


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
    }


def _trim_text(value: object) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text[:MAX_TEXT_CHARS] if text else None
