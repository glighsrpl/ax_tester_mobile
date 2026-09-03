"""Execution support for deterministic mobile accessibility checks."""

import importlib
import inspect
import pkgutil

from mobile_agents.static_agent.consumers.base import BaseConsumer, BaseSnapshotConsumer
from schemas import Issue
from tools.base import MobileElementInfo
from tools.mobile_screen_scanner import MobileScanSnapshot


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

    def rules_by_level(self) -> dict[str, int]:
        """Return the number of distinct WCAG rules evaluated by each consumer."""
        rules = {
            rule
            for consumer in [*self.element_consumers, *self.snapshot_consumers]
            if (rule := _consumer_rule(consumer))
        }
        return {level: sum(f"(Level {level})" in rule for rule in rules) for level in ("A", "AA", "AAA")}

    def _consume_snapshot(self, snapshot: MobileScanSnapshot) -> list[Issue]:
        return [
            issue.model_copy(update={"source": "deterministic_analyzer"})
            for consumer in self.snapshot_consumers
            for issue in consumer.consume(snapshot)
        ]

    def _consume_element(self, element: MobileElementInfo) -> list[Issue]:
        issues: list[Issue] = []
        for consumer in self.element_consumers:
            issues.extend(
                issue.model_copy(update={"source": "deterministic_analyzer"})
                for issue in consumer.consume(element)
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


def _consumer_rule(consumer: BaseConsumer | BaseSnapshotConsumer) -> str:
    module = inspect.getmodule(type(consumer))
    rule = getattr(module, "WCAG_RULE", "") if module is not None else ""
    return rule if isinstance(rule, str) else ""
