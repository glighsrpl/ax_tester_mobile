from dataclasses import dataclass

_IN_PLACE_CONTROL_CLASS_NAMES = (
    "checkbox",
    "switch",
    "togglebutton",
    "radiobutton",
    "seekbar",
    "compoundbutton",
    "ratingbar",
)


@dataclass
class MobileElementInfo:
    """Mobile element information extracted from the accessibility tree, including its index, text, content description, resource ID, class name, package, bounds, and various state attributes."""

    index: int
    text: str | None = None
    content_desc: str | None = None
    resource_id: str | None = None
    class_name: str | None = None
    package: str | None = None
    bounds: str | None = None
    clickable: bool = False
    focusable: bool = False
    enabled: bool = True
    selected: bool = False
    checked: bool | None = None
    expanded: bool | None = None
    page_screenshot: str | None = None
    element_screenshot: str | None = None
    focused: bool = False
    hint: str | None = None
    label_for: str | None = None
    input_type: str | None = None
    parent_index: int | None = None
    important_for_accessibility: str | None = None
    font_size: float | None = None
    font_style: str | None = None

    def get_label(self) -> str:
        return self.content_desc or self.text or self.resource_id or ""

    def get_focus_key(self) -> str:
        return f"idx:{self.index}:bounds:{self.bounds or ''}"

    def is_interactive(self) -> bool:
        return self.clickable or self.focusable


def is_in_place_control(element: MobileElementInfo) -> bool:
    """Return whether an element is a control that updates in place."""
    class_name = (element.class_name or "").casefold()
    return any(name in class_name for name in _IN_PLACE_CONTROL_CLASS_NAMES)


@dataclass
class MobileNavigatorState:
    """Mobile navigation state at a specific point in time, including the current activity, path taken, and the currently focused element."""

    path: list[str]
    activity: str | None = None
    root_element: MobileElementInfo | None = None
    previous_element: MobileElementInfo | None = None
    current_element: MobileElementInfo | None = None
    accessibility_tree: str | None = None
    page_screenshot: str | None = None


@dataclass
class MobileKeyboardResult:
    """Keyboard traversal elements and detected focus traps for one mobile screen."""

    reachable: list[MobileElementInfo]
    unreachable: list[MobileElementInfo]
    focus_order: list[MobileElementInfo]
    traps: list[dict]
    activity: str
