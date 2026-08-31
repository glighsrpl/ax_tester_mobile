from abc import ABC, abstractmethod
from typing import Any

from tools.base import NavigatorState


class BaseConsumer(ABC):
    """Base class for navigator state consumers."""

    name: str = "base-consumer"
    report_key: str = "report-key"

    @abstractmethod
    def consume(self, state: NavigatorState, **kwargs) -> None:
        """Consume a navigation state."""

    @abstractmethod
    def finalize(self) -> dict[str, Any]:
        """Return aggregated results."""
