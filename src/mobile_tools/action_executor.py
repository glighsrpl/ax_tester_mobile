import re
from dataclasses import dataclass
from typing import Literal

from mobile_tools.base import MobileElementInfo
from mobile_tools.tree import get_interactive_elements, parse_mobile_tree
from mobile_tools.utils.session import MOBILE_SESSION

PositionHint = Literal["bottom_right", "bottom_left", "top_right", "top_left", "center"]


@dataclass(frozen=True)
class MobileTapAction:
    "Represents a tap action to be executed on the mobile device."

    target: str
    position_hint: PositionHint | None = None


class MobileActionExecutor:
    """Executes actions on a mobile device using the MOBILE_SESSION."""

    async def tap(self, action: MobileTapAction) -> str:
        tree = await MOBILE_SESSION.get_accessibility_tree()
        elements = get_interactive_elements(parse_mobile_tree(tree))
        target = self._find_target(elements, action)
        if target is None or not target.bounds:
            raise RuntimeError(f"Cannot find tappable target: {action.target}")
        await MOBILE_SESSION.tap_bounds(target.bounds)
        return f"tap:{action.target}"

    def _find_target(
        self,
        elements: list[MobileElementInfo],
        action: MobileTapAction,
    ) -> MobileElementInfo | None:
        query = _normalize(action.target)
        matches = [element for element in elements if query in _normalize(element.get_label())]
        if not matches:
            matches = [element for element in elements if query in _normalize(element.resource_id or "")]
        if not matches:
            return None
        return min(matches, key=lambda element: self._position_score(element, action.position_hint))

    def _position_score(self, element: MobileElementInfo, hint: PositionHint | None) -> int:
        if not hint or not element.bounds:
            return 0
        left, top, right, bottom = map(int, re.findall(r"\d+", element.bounds)[:4])
        x = (left + right) // 2
        y = (top + bottom) // 2
        if hint == "bottom_right":
            return -x - y
        if hint == "bottom_left":
            return x - y
        if hint == "top_right":
            return -x + y
        if hint == "top_left":
            return x + y
        return abs(x) + abs(y)


def _normalize(value: str) -> str:
    return " ".join(value.casefold().split())
