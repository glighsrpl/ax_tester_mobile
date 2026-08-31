import json
from collections.abc import Mapping
from typing import Any

from google.adk.agents import SequentialAgent
from google.adk.agents.callback_context import CallbackContext

from common import MobileContextKey
from mobile_agents.static_agent.deterministic_consumers import run_deterministic_checks
from mobile_agents.static_agent.init_agent import init_agent
from schemas import Report


def merge_static_results(callback_context: CallbackContext) -> None:
    """Append deterministic issues to the report produced by the LLM sub-agent."""
    report = _report_mapping(callback_context.state)
    deterministic_issues = _state_issues(callback_context.state)
    llm_issues = report.get("issue_list", [])
    report["issue_list"] = [*deterministic_issues, *llm_issues]
    report["total_issues"] = len(report["issue_list"])
    callback_context.state[MobileContextKey.STATIC_RESULTS] = report


def _report_mapping(state: Mapping[Any, Any]) -> dict[str, Any]:
    report = state.get(MobileContextKey.STATIC_RESULTS, {})
    if isinstance(report, Report):
        return report.model_dump()
    if isinstance(report, str):
        try:
            report = json.loads(report)
        except json.JSONDecodeError:
            report = {}
    return dict(report) if isinstance(report, Mapping) else {}


def _state_issues(state: Mapping[Any, Any]) -> list[dict[str, Any]]:
    issues = state.get(MobileContextKey.DETERMINISTIC_ISSUES, [])
    return [issue for issue in issues if isinstance(issue, dict)] if isinstance(issues, list) else []


mobile_static_analysis_agent = SequentialAgent(
    name="MobileStaticAnalysisAgent",
    description="Run WCAG static analysis on mobile snapshots.",
    sub_agents=[init_agent],
    #before_agent_callback=run_deterministic_checks,
    #after_agent_callback=merge_static_results,
)
