"""Shared abstractions for deterministic mobile accessibility consumers."""

from abc import ABC, abstractmethod

from mobile_tools.base import MobileElementInfo
from mobile_tools.screen_scanner import MobileScanSnapshot
from schemas import Issue


class BaseConsumer(ABC):
    """Detect accessibility issues for one mobile element."""

    @abstractmethod
    def consume(self, element: MobileElementInfo) -> list[Issue]:
        """Return all issues detected for ``element``."""


class BaseSnapshotConsumer(ABC):
    """Detect accessibility issues that depend on a complete screen snapshot."""

    @abstractmethod
    def consume(self, snapshot: MobileScanSnapshot) -> list[Issue]:
        """Return all issues detected for ``snapshot``."""
