"""Run deterministic consumers against serialized mobile scan snapshots."""

from collections.abc import Mapping
from typing import Any

from google.adk.agents.callback_context import CallbackContext

from common import MobileContextKey
from mobile_agents.static_agent.consumers.deterministic.runner import DeterministicRunner
from schemas import Issue
from tools.mobile_base import MobileElementInfo
from tools.mobile_screen_scanner import MobileScanSnapshot


def run_deterministic_analysis(snapshot: MobileScanSnapshot) -> list[Issue]:
    """Run deterministic checks for one mobile screen snapshot."""
    return DeterministicRunner().run(snapshot)


def run_deterministic_checks(callback_context: CallbackContext) -> None:
    """Execute deterministic checks before the LLM sub-agent runs."""
    navigator_data = _state_mapping(callback_context.state, MobileContextKey.NAVIGATOR_DATA)
    callback_context.state[MobileContextKey.DETERMINISTIC_ISSUES] = [
        issue.model_dump()
        for snapshot_data in _snapshot_payloads(navigator_data)
        for issue in run_deterministic_analysis(_snapshot_from_data(snapshot_data))
    ]


def _snapshot_from_data(data: Mapping[str, Any]) -> MobileScanSnapshot:
    elements = [
        MobileElementInfo(**element_data)
        for element_data in data.get("elements", [])
        if isinstance(element_data, Mapping)
    ]
    return MobileScanSnapshot(
        activity=str(data.get("activity", "")),
        tree_xml=str(data.get("tree_xml", "")),
        screenshot=str(data.get("screenshot", "")),
        elements=elements,
        snapshot_id=str(data.get("snapshot_id", "")),
    )


def _snapshot_payloads(navigator_data: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    snapshots = navigator_data.get("snapshots")
    if isinstance(snapshots, list):
        return [snapshot for snapshot in snapshots if isinstance(snapshot, Mapping)]
    return [navigator_data] if isinstance(navigator_data.get("elements"), list) else []


def _state_mapping(state: Mapping[Any, Any], key: MobileContextKey) -> Mapping[str, Any]:
    value = state.get(key, {})
    return value if isinstance(value, Mapping) else {}
