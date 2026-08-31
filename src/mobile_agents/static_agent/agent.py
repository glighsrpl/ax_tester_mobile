from __future__ import annotations

from typing import TYPE_CHECKING

from mobile_tools.base import MobileKeyboardResult, MobileNavigatorState
from mobile_tools.consumers import MobileBaseConsumer
from mobile_tools.tree import get_interactive_elements

if TYPE_CHECKING:
    from mobile_tools.screen_scanner import MobileScanSnapshot


class MobileStaticAgent:
    """Run mobile accessibility consumers against captured screen data."""

    def __init__(self, consumers: list[MobileBaseConsumer]) -> None:
        self.consumers = consumers

    def consume_screen(
        self,
        snapshot: MobileScanSnapshot,
        keyboard_result: MobileKeyboardResult | None = None,
    ) -> None:
        # TODO: now only for deterministic consumer, need to be extendend for non-deterministic consumer (LLM based)
        for element in get_interactive_elements(snapshot.elements):
            state = MobileNavigatorState(
                path=[],
                activity=snapshot.activity,
                current_element=element,
                accessibility_tree=snapshot.tree_xml,
                page_screenshot=snapshot.screenshot,
            )
            for consumer in self.consumers:
                consumer.consume(state)

        if keyboard_result is not None:
            for consumer in self.consumers:
                consumer.consume_keyboard(keyboard_result)

    def finalize(self) -> list[dict]:
        return [
            {"report_key": consumer.report_key, "result": consumer.finalize()} for consumer in self.consumers
        ]
