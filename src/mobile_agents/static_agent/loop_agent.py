"""Iterative discovery of mobile WCAG issues missed by the initial analysis."""

import json
import re
from collections.abc import Mapping
from typing import Any

from google.adk.agents import LoopAgent, SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from mobile_agents.static_agent.init_agent import _mobile_wcag_rules, init_agent
from schemas import Issue, Report

MAX_ADDITIONAL_PASSES = 2
RESOURCE_ID_PATTERN = re.compile(r"resource[-_]id\s*[=:]\s*[\"']?([^\"'\s,}]+)", re.IGNORECASE)
XPATH_PATTERN = re.compile(r"xpath\s*[=:]\s*[\"']?([^\"'\s,}]+)", re.IGNORECASE)


def get_mobile_loop_instruction(tool_context: ToolContext) -> str:
    snapshot_data = _state_value(tool_context.state, MobileContextKey.NAVIGATOR_DATA, {})
    platform = str(_state_value(tool_context.state, MobileContextKey.PLATFORM, ""))
    wcag_rules = _mobile_wcag_rules(platform)
    existing_issues = _compact_issues(_loop_report(tool_context.state).issue_list)
    return f"""
        Re-audit the attached mobile accessibility snapshot for issues missed by an
        earlier pass. The screenshot and snapshot data are the same evidence supplied
        to the initial analysis.

        ## EVIDENCE POLICY — ZERO FALSE POSITIVES
        - Report ONLY a concrete, provable WCAG violation in the supplied evidence.
        - Do not repeat any issue in the existing issue list, including the same WCAG
          rule on the same xpath or resource-id.
        - If evidence is insufficient, mark the rule PASS and do not create an issue.

        ## REQUIRED RULE-BY-RULE REVIEW
        - Review every rule for distinct nodes not already in the existing issue list.
          For every rule not represented in that list, perform an explicit PASS/FAIL
          review to guarantee complete coverage.
        - For each uncovered rule, record PASS or FAIL in metadata as
          key="rule_status:<rule id>", value="PASS" or "FAIL".
        - Emit issues only for FAIL rules. A PASS produces no issue.
        - In html_snippet include element index, bounds, class, activity, snapshot_id,
          and xpath or resource-id when available.

        Return only the Report schema. Use source "llm", preserve the current mobile
        activity as page, and set total_issues to the issue_list length.

        Existing issues (r=rule, n=node identifier, d=description):
        {json.dumps(existing_issues, ensure_ascii=False, separators=(",", ":"))}

        WCAG mobile rules to review:
        {json.dumps(wcag_rules, ensure_ascii=False, separators=(",", ":"))}

        Snapshot data:
        {json.dumps(snapshot_data, ensure_ascii=False, default=str)}
    """


def merge_loop_pass(callback_context: CallbackContext) -> None:
    pass_report = _report_from_value(_state_value(callback_context.state, MobileContextKey.LOOP_REPORT, {}))
    static_report = _report_from_value(_state_value(callback_context.state, MobileContextKey.STATIC_RESULTS, {}))
    new_issues = _new_issues(static_report.issue_list, pass_report.issue_list)
    enriched_report = _with_issues(static_report, new_issues)
    callback_context.state[MobileContextKey.LOOP_REPORT] = enriched_report
    callback_context.state[MobileContextKey.STATIC_RESULTS] = enriched_report
    if not new_issues:
        callback_context._event_actions.escalate = True


def _state_value(state: Mapping[Any, Any], key: MobileContextKey, default: Any) -> Any:
    return state.get(key) or state.get(str(key), default)


def _loop_report(state: Mapping[Any, Any]) -> Report:
    static_report = _state_value(state, MobileContextKey.STATIC_RESULTS, {})
    return _report_from_value(_state_value(state, MobileContextKey.LOOP_REPORT, static_report))


def _report_from_value(value: object) -> Report:
    if isinstance(value, str):
        return Report.model_validate_json(value)
    return Report.model_validate(value)


def _with_issues(report: Report, new_issues: list[Issue]) -> dict[str, Any]:
    issues = [*report.issue_list, *new_issues]
    return report.model_copy(update={"issue_list": issues, "total_issues": len(issues)}).model_dump(mode="json")


def _new_issues(existing_issues: list[Issue], candidates: list[Issue]) -> list[Issue]:
    known_keys = {_issue_key(issue) for issue in existing_issues}
    new_issues: list[Issue] = []
    for issue in candidates:
        issue_key = _issue_key(issue)
        if issue_key not in known_keys:
            known_keys.add(issue_key)
            new_issues.append(issue)
    return new_issues


def _compact_issues(issues: list[Issue]) -> list[dict[str, str]]:
    return [
        {
            "r": issue.wcag_rule,
            "n": _node_identifier(issue),
            "d": " ".join(issue.description.split()),
        }
        for issue in issues
    ]


def _issue_key(issue: Issue) -> tuple[str, str]:
    return issue.wcag_rule, _node_identifier(issue)


def _node_identifier(issue: Issue) -> str:
    for pattern in (RESOURCE_ID_PATTERN, XPATH_PATTERN):
        match = pattern.search(issue.html_snippet)
        if match:
            return match.group(1)
    return f"issue:{issue.id}"


loop_pass_agent = LlmAgent(
    name="MobileStaticLoopPassAgent",
    model=MODEL,
    description="Find new WCAG issues not found by the initial mobile analysis.",
    instruction=get_mobile_loop_instruction,
    output_schema=Report,
    output_key=MobileContextKey.LOOP_REPORT,
    after_agent_callback=merge_loop_pass,
)

mobile_loop_agent = SequentialAgent(
    name="MobileLoopAgent",
    description="Enrich mobile static-analysis results with up to two issue-discovery passes.",
    sub_agents=[
        init_agent,
        LoopAgent(
            name="MobileStaticIssueLoop",
            sub_agents=[loop_pass_agent],
            max_iterations=MAX_ADDITIONAL_PASSES,
        ),
    ],
)
