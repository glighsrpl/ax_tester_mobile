import json
from collections.abc import Mapping
from typing import Any

from google.adk.agents import SequentialAgent
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from mobile_agents.static_agent.contrast_agent import contrast_agent
from mobile_agents.static_agent.cross_screen_agent import cross_screen_agent
from mobile_agents.static_agent.loop_agent import mobile_loop_agent
from schemas import Issue, Report, ScoreInfo
from schemas.issues import WCAG_LEVEL_WEIGHTS


def get_mobile_merge_instruction(tool_context: ToolContext) -> str:
    """Build the merge prompt from the separate deterministic and LLM reports."""
    deterministic_report = _state_report(tool_context, MobileContextKey.DETERMINISTIC_REPORT)
    contrast_report = _state_report(tool_context, MobileContextKey.CONTRAST_REPORT)
    llm_report = _state_report(tool_context, MobileContextKey.LLM_REPORT)
    return f"""
        Merge the following mobile accessibility reports into a single Report schema.

        INSTRUCTIONS:

        1. For each finding, extract the values of "activity" and "bounds" from inside its html_snippet. Use these ONLY to build the identity key — never modify the snippet.

        2. Identity key = (wcag_rule, activity extracted from snippet, bounds extracted from snippet, image_url_or_path, failure type/description semantically equivalent). Two findings with the same identity key are DUPLICATES.

        3. If two or more findings share the same identity key → emit ONE issue:
        - Keep the html_snippet from the contrast agent source (it is longer and contains measurement fields). Emit it VERBATIM.
        - Set source = "both".
        - wcag_rule, image_url_or_path, and activity must be reported VERBATIM.
        - Merge all other fields from the duplicate findings, keeping the most complete values.

        4. If a finding has no duplicate → emit it unchanged with ALL its original source value. All the fields must be reported VERBATIM.

        5. Never modify, truncate, summarize, or reformat any html_snippet.

        6. Different wcag_rule, different activity, different bounds, different image_url_or_path, or different failure type → DISTINCT issues, even if they target the same element.

        7. Source values:
        - "deterministic_analyzer" — found only by deterministic analyzer
        - "llm/contrast_agent" — found only by contrast agent
        - "llm" — found only by LLM agent
        - "both" — found by ≥ 2 agents (merged)

        8. The score_passed, score_total, and total_issues fields are recalculated
        deterministically in code after the merge. Return valid placeholder values.

        9. Return ONLY the Report schema. Do NOT include input reports.

        Deterministic report:
        {json.dumps(deterministic_report, ensure_ascii=False)}

        Contrast report:
        {json.dumps(contrast_report, ensure_ascii=False)}

        Per-screen LLM report:
        {json.dumps(llm_report, ensure_ascii=False)}
    """


def _state_report(tool_context: ToolContext, key: MobileContextKey) -> dict[str, Any]:
    report = tool_context.state.get(key) or tool_context.state.get(str(key), {})
    if isinstance(report, Report):
        return report.model_dump()
    if isinstance(report, str):
        try:
            report = json.loads(report)
        except json.JSONDecodeError:
            report = {}
    return dict(report) if isinstance(report, Mapping) else {}


def merge_report_scores(reports: list[Report]) -> tuple[ScoreInfo, ScoreInfo, int]:
    """Combine report totals and derive passed scores from unique merged issues."""
    score_total = ScoreInfo(
        **{
            f"level_{level}": sum(getattr(report.score_total, f"level_{level}") for report in reports)
            for level in WCAG_LEVEL_WEIGHTS
        }
    )
    merged_issues = _deduplicated_issues(reports)
    score_passed = _score_passed(score_total, merged_issues)
    return score_total, score_passed, len(merged_issues)


def _score_passed(score_total: ScoreInfo, issues: list[Issue]) -> ScoreInfo:
    issue_counts = {
        level: sum(f"(Level {level})" in issue.wcag_rule for issue in issues) for level in WCAG_LEVEL_WEIGHTS
    }
    return ScoreInfo(
        **{
            f"level_{level}": getattr(score_total, f"level_{level}") - issue_counts[level] * weight
            for level, weight in WCAG_LEVEL_WEIGHTS.items()
        }
    )


def fix_merged_report_scores(callback_context: CallbackContext) -> None:
    """Replace merge-agent score fields with deterministic aggregate values."""
    state = callback_context.state
    reports = [
        _report_from_state(state, MobileContextKey.DETERMINISTIC_REPORT),
        _report_from_state(state, MobileContextKey.CONTRAST_REPORT),
        _report_from_state(state, MobileContextKey.LLM_REPORT),
    ]
    score_total, _, _ = merge_report_scores(reports)
    merged_report = _report_from_state(state, MobileContextKey.STATIC_RESULTS)
    state[MobileContextKey.STATIC_RESULTS] = merged_report.model_copy(
        update={
            "score_total": score_total,
            "score_passed": _score_passed(score_total, merged_report.issue_list),
            "total_issues": len(merged_report.issue_list),
        }
    ).model_dump(mode="json")


def _report_from_state(state: Mapping[Any, Any], key: MobileContextKey) -> Report:
    value = state.get(key) or state.get(str(key), {})
    return Report.model_validate_json(value) if isinstance(value, str) else Report.model_validate(value)


def _deduplicated_issues(reports: list[Report]) -> list[Issue]:
    issues_by_content = {}
    for report in reports:
        for issue in report.issue_list:
            issue_key = issue.model_dump_json(exclude={"source"})
            issues_by_content.setdefault(issue_key, issue)
    return list(issues_by_content.values())


mobile_static_analysis_agent = SequentialAgent(
    name="MobileStaticAnalysisAgent",
    description="Run WCAG static analysis on mobile snapshots.",
    sub_agents=[contrast_agent, mobile_loop_agent],
)

mobile_static_post_pass_agent = SequentialAgent(
    name="MobileStaticPostPassAgent",
    description="Run static analysis checks that require multiple mobile screens.",
    sub_agents=[cross_screen_agent],
)

mobile_merge_agent = LlmAgent(
    name="MobileMergeReportsAgent",
    model=MODEL,
    description="Merge deterministic and LLM mobile accessibility reports.",
    instruction=get_mobile_merge_instruction,
    output_schema=Report,
    output_key=MobileContextKey.STATIC_RESULTS,
    after_agent_callback=fix_merged_report_scores,
)
