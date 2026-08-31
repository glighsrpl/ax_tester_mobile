from abc import ABC, abstractmethod
from typing import Any

from mobile_tools.base import MobileKeyboardResult, MobileNavigatorState


class MobileBaseConsumer(ABC):
    """Abstract base class for mobile navigation consumers."""

    name: str = "mobile-base-consumer"
    report_key: str = "mobile-report-key"

    @abstractmethod
    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        """Consume a mobile navigation state."""

    def consume_keyboard(self, data: MobileKeyboardResult) -> None:
        """Consume a completed mobile keyboard traversal."""
        return None

    @abstractmethod
    def finalize(self) -> dict[str, Any]:
        """Return aggregated results."""
