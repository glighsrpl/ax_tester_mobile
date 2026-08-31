import logging
from dataclasses import asdict, dataclass
from typing import Any

from mobile_tools.base import MobileElementInfo, MobileKeyboardResult, MobileNavigatorState
from mobile_tools.consumers import MobileBaseConsumer
from mobile_tools.tree import get_interactive_elements, parse_mobile_tree
from mobile_tools.utils.session import MOBILE_SESSION
from tools.base import Tool, ToolResult, ToolStatus

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _KeyboardSnapshot:
    activity: str
    tree_xml: str
    screenshot: str
    elements: list[MobileElementInfo]


class MobileKeyboardScannerTool(Tool):
    """Traverse mobile focus with the D-pad and report reachability and traps."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        configured_steps = self.config.get("max_focus_steps")
        self.max_focus_steps = int(configured_steps) if configured_steps is not None else None
        configured_budget = self.config.get("step_budget")
        self._step_budget = int(configured_budget) if configured_budget is not None else None
        self.consumers: list[MobileBaseConsumer] = list(self.config.get("consumers") or [])

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            initial = await self._snapshot()
            expected_elements = get_interactive_elements(initial.elements)
            expected_by_key = {element.get_focus_key(): element for element in expected_elements}
            expected_order = list(expected_by_key)
            expected = set(expected_order)  # set of all expected focus keys for quick lookup
            configured_steps = kwargs.get("max_focus_steps", self.max_focus_steps)
            step_limit = (
                2 * len(expected_elements) if configured_steps is None else max(int(configured_steps), 0)
            )  # max steps to take during focus traversal
            if self._step_budget is not None:
                step_limit = min(step_limit, max(self._step_budget, 0))

            reached: set[str] = set()
            reached_elements: dict[str, MobileElementInfo] = {}
            focused_elements: list[MobileElementInfo] = []
            traps: list[str] = []
            trap_data: list[dict] = []
            total_steps = 0
            previous: MobileElementInfo | None = None

            while total_steps < step_limit:
                snapshot, focused = await self._advance_focus()
                total_steps += 1
                if focused is None:
                    continue
                key = focused.get_focus_key()
                focused_elements.append(focused)
                self._consume_focus(snapshot, focused, previous, total_steps)
                previous = focused

                if key not in reached:
                    reached.add(key)
                    reached_elements[key] = focused
                    continue
                if expected.issubset(reached):
                    # All expected elements have been reached
                    break
                if key not in traps:
                    traps.append(key)
                    trap_data.append({"focus_key": key, "step": total_steps})
                if total_steps >= step_limit:
                    break

                snapshot, focused = await self._advance_focus()
                total_steps += 1
                if focused is None:
                    break
                key = focused.get_focus_key()
                focused_elements.append(focused)
                self._consume_focus(snapshot, focused, previous, total_steps)
                previous = focused
                if key in reached:
                    # element has already been reached, so we are in a trap
                    break
                reached.add(key)
                reached_elements[key] = focused

            keyboard_result = MobileKeyboardResult(
                reachable=[reached_elements[key] for key in expected_order if key in reached_elements],
                unreachable=[expected_by_key[key] for key in expected_order if key not in reached],
                focus_order=focused_elements,
                traps=trap_data,
                activity=initial.activity,
            )
            for consumer in self.consumers:
                try:
                    consumer.consume_keyboard(keyboard_result)
                except Exception:
                    logger.exception("Mobile keyboard result consumer failed: %s", consumer.name)

            data = {
                "reachable": [asdict(element) for element in keyboard_result.reachable],
                "unreachable": [asdict(element) for element in keyboard_result.unreachable],
                "focus_order": [asdict(element) for element in keyboard_result.focus_order],
                "traps": trap_data,
                "total_steps": total_steps,
                "activity": initial.activity,
            }
            return ToolResult(
                "mobile-keyboard-scanner",
                ToolStatus.SUCCESS,
                data,
                metadata={"expected_count": len(expected)},
            )
        except Exception as exc:
            logger.exception("Mobile keyboard scanner failed")
            return ToolResult("mobile-keyboard-scanner", ToolStatus.FAILURE, {}, error=str(exc))

    async def _snapshot(self) -> _KeyboardSnapshot:
        tree = await MOBILE_SESSION.get_accessibility_tree()
        screenshot = await MOBILE_SESSION.take_screenshot()
        activity = await MOBILE_SESSION.get_current_activity()
        return _KeyboardSnapshot(
            activity=activity.strip() or "unknown",
            tree_xml=tree,
            screenshot=screenshot,
            elements=parse_mobile_tree(tree, page_screenshot=screenshot),
        )

    async def _advance_focus(self) -> tuple[_KeyboardSnapshot, MobileElementInfo | None]:
        await MOBILE_SESSION.press_dpad_down()
        snapshot = await self._snapshot()
        return snapshot, next((element for element in snapshot.elements if element.focused), None)

    def _consume_focus(
        self,
        snapshot: _KeyboardSnapshot,
        focused: MobileElementInfo,
        previous: MobileElementInfo | None,
        total_steps: int,
    ) -> None:
        state = MobileNavigatorState(
            path=["dpad_down"] * total_steps,
            activity=snapshot.activity,
            previous_element=previous,
            current_element=focused,
            accessibility_tree=snapshot.tree_xml,
            page_screenshot=snapshot.screenshot,
        )
        for consumer in self.consumers:
            try:
                consumer.consume(state)
            except Exception:
                logger.exception("Mobile keyboard consumer failed: %s", consumer.name)
