"""Shared abstractions for deterministic mobile accessibility consumers."""

from abc import ABC, abstractmethod

from schemas import Issue
from tools.mobile_base import MobileElementInfo
from tools.mobile_screen_scanner import MobileScanSnapshot


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
