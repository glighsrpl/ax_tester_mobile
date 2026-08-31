import asyncio
import logging
from typing import Any

from tools.base import Tool, ToolResult, ToolStatus
from tools.mobile_base import MobileElementInfo, MobileNavigatorState
from tools.mobile_consumers import MobileBaseConsumer, build_default_mobile_consumers
from tools.mobile_tree import bounds_size, get_interactive_elements, get_screen_id, parse_mobile_tree
from utils.mobile_session import MOBILE_SESSION

logger = logging.getLogger(__name__)


class MobileRuntimeNavigatorTool(Tool):
    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.max_steps = self.config.get("max_steps", 100)
        self.initial_wait_ms = self.config.get("initial_wait_ms", 3000)
        self.consumers: list[MobileBaseConsumer] = (
            self.config.get("consumers") or build_default_mobile_consumers()
        )

    async def execute(self, **kwargs) -> ToolResult:
        try:
            if not MOBILE_SESSION.is_initialized():
                raise RuntimeError("Mobile session not initialized")

            data = await self._run_navigation(
                max_steps=kwargs.get("max_steps", self.max_steps),
                initial_wait_ms=kwargs.get("initial_wait_ms", self.initial_wait_ms),
            )
            return ToolResult(
                tool_name="mobile-runtime-navigator",
                status=ToolStatus.SUCCESS,
                data=data,
                metadata={"screen_count": len(data.get("visited_screens", []))},
            )
        except Exception as exc:
            logger.exception("Mobile runtime navigator failed")
            return ToolResult(
                tool_name="mobile-runtime-navigator",
                status=ToolStatus.FAILURE,
                data={},
                error=str(exc),
            )

    async def _run_navigation(self, max_steps: int, initial_wait_ms: int) -> dict[str, Any]:
        path: list[str] = []
        seen_taps: set[str] = set()
        seen_scrolls: set[str] = set()
        visited_screens: list[str] = []
        first_screenshot: str | None = None
        previous_element: MobileElementInfo | None = None
        screen_size = await MOBILE_SESSION.get_window_size()
        depth = 0

        await asyncio.sleep(initial_wait_ms / 1000)

        for step in range(max_steps):
            tree, screenshot, screen_id, elements = await self._snapshot()
            if first_screenshot is None:
                first_screenshot = screenshot
            if screen_id not in visited_screens:
                visited_screens.append(screen_id)

            previous_element = self._consume_elements(
                elements,
                path=path,
                screen_id=screen_id,
                tree=tree,
                screenshot=screenshot,
                previous_element=previous_element,
            )

            target = self._next_target(elements, seen_taps, screen_size)
            if target:
                seen_taps.add(target.get_focus_key())
                path.append(f"tap:{target.index}")
                logger.info("Mobile navigator tapping %s", self._describe(target))
                await MOBILE_SESSION.tap_bounds(target.bounds or "")
                if await self._current_screen_id() != screen_id:
                    depth += 1
                continue

            if screen_id not in seen_scrolls:
                seen_scrolls.add(screen_id)
                path.append("scroll_down")
                logger.info("Mobile navigator scrolling down on %s", screen_id)
                await MOBILE_SESSION.scroll_down()
                if await self._current_screen_id() != screen_id:
                    continue

            if depth <= 0:
                return self._result(first_screenshot, visited_screens, path, step + 1)

            path.append("back")
            logger.info("Mobile navigator pressing back")
            await MOBILE_SESSION.back()
            depth -= 1

        return self._result(first_screenshot, visited_screens, path, max_steps)

    async def _snapshot(self) -> tuple[str, str, str, list[MobileElementInfo]]:
        tree = await MOBILE_SESSION.get_accessibility_tree()
        screenshot = await MOBILE_SESSION.take_screenshot()
        screen_id = get_screen_id(tree)
        return (
            tree,
            screenshot,
            screen_id,
            parse_mobile_tree(tree, page_screenshot=screenshot, screen_id=screen_id),
        )

    async def _current_screen_id(self) -> str:
        return get_screen_id(await MOBILE_SESSION.get_accessibility_tree())

    def _consume_elements(
        self,
        elements: list[MobileElementInfo],
        *,
        path: list[str],
        screen_id: str,
        tree: str,
        screenshot: str,
        previous_element: MobileElementInfo | None,
    ) -> MobileElementInfo | None:
        for element in get_interactive_elements(elements):
            state = MobileNavigatorState(
                path=path.copy(),
                screen_id=screen_id,
                previous_element=previous_element,
                current_element=element,
                accessibility_tree=tree,
                page_screenshot=screenshot,
            )
            for consumer in self.consumers:
                try:
                    consumer.consume(state)
                except Exception:
                    logger.exception("Mobile consumer %s failed", consumer.name)
            previous_element = element
        return previous_element

    def _next_target(
        self,
        elements: list[MobileElementInfo],
        seen_taps: set[str],
        screen_size: dict[str, int],
    ) -> MobileElementInfo | None:
        candidates = [
            element
            for element in get_interactive_elements(elements)
            if element.bounds and element.get_focus_key() not in seen_taps
        ]
        useful = [
            element
            for element in candidates
            if self._target_area(element) < self._screen_area(screen_size) * 0.85
        ]
        candidates = useful or candidates
        return min(candidates, key=self._target_score, default=None)

    def _target_score(self, element: MobileElementInfo) -> tuple[int, int, int, int]:
        return (
            0 if element.clickable else 1,
            0 if element.get_label() or element.resource_id else 1,
            self._target_area(element),
            element.index,
        )

    def _target_area(self, element: MobileElementInfo) -> int:
        try:
            width, height = bounds_size(element.bounds or "")
            return width * height
        except ValueError:
            return 0

    def _screen_area(self, size: dict[str, int]) -> int:
        return int(size.get("width", 0)) * int(size.get("height", 0)) or 1

    def _describe(self, element: MobileElementInfo) -> str:
        label = element.get_label() or element.resource_id or element.class_name or "element"
        return f"{element.index}:{label}:{element.bounds or '-'}"

    def _result(
        self,
        page_screenshot: str | None,
        visited_screens: list[str],
        path: list[str],
        steps: int,
    ) -> dict[str, Any]:
        return {
            "page_screenshot": page_screenshot,
            "visited_screens": visited_screens,
            "path": path,
            "steps": steps,
            "consumer_results": self._finalize_consumers(),
        }

    def _finalize_consumers(self) -> list[dict[str, Any]]:
        results = []
        for consumer in self.consumers:
            try:
                results.append({"report_key": consumer.report_key, "result": consumer.finalize()})
            except Exception:
                logger.exception("Mobile consumer %s finalize error", consumer.name)
        return results
