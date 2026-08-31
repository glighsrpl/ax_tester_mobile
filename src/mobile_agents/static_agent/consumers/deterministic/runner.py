"""Execution support for deterministic mobile accessibility checks."""

import importlib
import inspect
import pkgutil

from mobile_agents.static_agent.consumers.base import BaseConsumer, BaseSnapshotConsumer
from mobile_tools.base import MobileElementInfo
from mobile_tools.screen_scanner import MobileScanSnapshot
from schemas import Issue


class DeterministicRunner:
    """Discover and execute element-level and snapshot-level consumers."""

    def __init__(self) -> None:
        self.element_consumers, self.snapshot_consumers = self._discover_consumers()

    def run(self, snapshot: MobileScanSnapshot) -> list[Issue]:
        """Run every discovered consumer against a snapshot and its elements."""
        issues = self._consume_snapshot(snapshot)
        for element in snapshot.elements:
            issues.extend(self._consume_element(element))
        return issues

    def _consume_snapshot(self, snapshot: MobileScanSnapshot) -> list[Issue]:
        return [
            issue.model_copy(update={"source": "deterministic"})
            for consumer in self.snapshot_consumers
            for issue in consumer.consume(snapshot)
        ]

    def _consume_element(self, element: MobileElementInfo) -> list[Issue]:
        issues: list[Issue] = []
        for consumer in self.element_consumers:
            issues.extend(
                issue.model_copy(update={"source": "deterministic"}) for issue in consumer.consume(element)
            )
        return issues

    @staticmethod
    def _discover_consumers() -> tuple[list[BaseConsumer], list[BaseSnapshotConsumer]]:
        package = importlib.import_module("mobile_agents.static_agent.consumers.deterministic")
        modules = [
            package,
            *(
                importlib.import_module(module_info.name)
                for module_info in pkgutil.iter_modules(package.__path__, f"{package.__name__}.")
            ),
        ]
        element_consumer_classes = {
            candidate
            for module in modules
            for _, candidate in inspect.getmembers(module, inspect.isclass)
            if issubclass(candidate, BaseConsumer) and candidate is not BaseConsumer
        }
        snapshot_consumer_classes = {
            candidate
            for module in modules
            for _, candidate in inspect.getmembers(module, inspect.isclass)
            if issubclass(candidate, BaseSnapshotConsumer) and candidate is not BaseSnapshotConsumer
        }
        return (
            [
                consumer_class()
                for consumer_class in sorted(element_consumer_classes, key=lambda item: item.__name__)
            ],
            [
                consumer_class()
                for consumer_class in sorted(snapshot_consumer_classes, key=lambda item: item.__name__)
            ],
        )
