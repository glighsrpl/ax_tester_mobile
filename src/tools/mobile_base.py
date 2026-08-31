from dataclasses import dataclass


@dataclass
class MobileElementInfo:
    index: int
    screen_id: str
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
    checked: bool = False
    page_screenshot: str | None = None
    element_screenshot: str | None = None

    def get_label(self) -> str:
        return self.content_desc or self.text or self.resource_id or ""

    def get_focus_key(self) -> str:
        return f"screen:{self.screen_id}:idx:{self.index}:bounds:{self.bounds or ''}"

    def is_interactive(self) -> bool:
        return self.clickable or self.focusable


@dataclass
class MobileNavigatorState:
    path: list[str]
    screen_id: str
    root_element: MobileElementInfo | None = None
    previous_element: MobileElementInfo | None = None
    current_element: MobileElementInfo | None = None
    accessibility_tree: str | None = None
    page_screenshot: str | None = None
