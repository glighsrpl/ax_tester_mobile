"""Shared abstraction for deterministic mobile accessibility consumers."""

from abc import ABC, abstractmethod

from mobile_tools.base import MobileElementInfo
from schemas import Issue


class BaseConsumer(ABC):
    """Detect accessibility issues for one mobile element."""

    @abstractmethod
    def consume(self, element: MobileElementInfo) -> list[Issue]:
        """Return all issues detected for ``element``."""
