"""Execution support for deterministic element-level accessibility checks."""

import importlib
import inspect
import pkgutil

from mobile_agents.static_agent.consumers.base import BaseConsumer
from mobile_tools.base import MobileElementInfo
from mobile_tools.screen_scanner import MobileScanSnapshot
from schemas import Issue


class DeterministicRunner:
    """Discover and execute deterministic consumers for each snapshot element."""

    def __init__(self) -> None:
        self.consumers = self._discover_consumers()

    def run(self, snapshot: MobileScanSnapshot) -> list[Issue]:
        """Run every discovered consumer against every element in a snapshot."""
        issues: list[Issue] = []
        for element in snapshot.elements:
            issues.extend(self._consume_element(element))
        return issues

    def _consume_element(self, element: MobileElementInfo) -> list[Issue]:
        issues: list[Issue] = []
        for consumer in self.consumers:
            issues.extend(
                issue.model_copy(update={"source": "deterministic"}) for issue in consumer.consume(element)
            )
        return issues

    @staticmethod
    def _discover_consumers() -> list[BaseConsumer]:
        package = importlib.import_module("mobile_agents.static_agent.consumers.deterministic")
        modules = [
            package,
            *(
                importlib.import_module(module_info.name)
                for module_info in pkgutil.iter_modules(package.__path__, f"{package.__name__}.")
            ),
        ]
        consumer_classes = {
            candidate
            for module in modules
            for _, candidate in inspect.getmembers(module, inspect.isclass)
            if issubclass(candidate, BaseConsumer) and candidate is not BaseConsumer
        }
        return [consumer_class() for consumer_class in sorted(consumer_classes, key=lambda item: item.__name__)]
