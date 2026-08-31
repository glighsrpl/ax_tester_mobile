from abc import ABC, abstractmethod
from typing import Any

from tools.mobile_base import MobileNavigatorState


class MobileBaseConsumer(ABC):
    name: str = "mobile-base-consumer"
    report_key: str = "mobile-report-key"

    @abstractmethod
    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        """Consume a mobile navigation state."""

    @abstractmethod
    def finalize(self) -> dict[str, Any]:
        """Return aggregated results."""
