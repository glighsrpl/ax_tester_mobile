"""LLM post-pass for accessibility checks spanning multiple mobile screens."""

import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from schemas import Report
from schemas.issues import fix_report_scores
from utils.report_store import REPORTS_ROOT

CROSS_SCREEN_RULES = (
    "1.3.1 - Info and Relationships (Level A)",
    "1.3.2 - Meaningful Sequence (Level A)",
    "2.4.3 - Focus Order (Level A)",
    "2.4.6 - Headings and Labels (Level AA)",
    "3.2.3 - Consistent Navigation (Level AA)",
    "3.2.4 - Consistent Identification (Level AA)",
)
CROSS_SCREEN_RULES_BY_LEVEL = {"A": 3, "AA": 3, "AAA": 0}
SNAPSHOT_ID_PATTERN = re.compile(r"\bsnapshot_id=([^\s;|]+)")


def get_cross_screen_instruction(
    tool_context: ToolContext,
    screenshots_dir: str | Path | None = None,  # TODO: pass from caller
) -> str:
    """Build the post-pass prompt from compact screen summaries only."""
    summaries = _screen_summaries(tool_context)
    snapshot_paths = _snapshot_paths(_summary_snapshot_ids(summaries), screenshots_dir)
    app_package = _state_text(tool_context, MobileContextKey.APP_PACKAGE)
    activity = _state_text(tool_context, MobileContextKey.APP_ACTIVITY)
    return f"""
        You are a cross-screen accessibility auditor for mobile applications.
        You receive accumulated per-screen summaries and must evaluate ONLY cross-screen
        consistency rules derived from WCAG 2.2.

        ## SCOPE
        - Evaluate only these WCAG rules: {json.dumps(CROSS_SCREEN_RULES)}
        - Do NOT re-evaluate single-screen rules.
        - Do NOT evaluate 3.2.6 (Consistent Help) — scope is limited to one activity.
        - Report a violation ONLY when summaries provide concrete evidence of inconsistency
        between comparable screens. If screens are not comparable or evidence is ambiguous,
        report nothing.

        ## COMPARABILITY
        All summaries belong to the same activity. Compare only the supplied screens.
        Minimum 2 comparable screens required to flag any issue.

        ## RULES

        ### 1.3.1 Info and Relationships (Level A)
        Compare programmatic structure of recurring components across screens.
        Flag: same logical component uses different roles or structural patterns.
        Evidence needed: role mismatch, container type change, or semantic grouping
        inconsistency for components serving the same purpose.

        ### 1.3.2 Meaningful Sequence (Level A)
        Compare reading order of analogous content blocks across screens with similar layouts.
        Flag: same layout type presents content in different logical order.
        Evidence needed: reordered headings, content sections, or grouped elements
        within otherwise identical layout structures.

        ### 2.4.3 Focus Order (Level A)
        Compare focusable_order across screens with similar layouts.
        Flag: logically equivalent interactive elements follow different traversal sequences.
        Evidence needed: same set of interactive elements traversed in conflicting order.

        ### 2.4.6 Headings and Labels (Level AA)
        Compare heading hierarchy and label descriptiveness across screens.
        Flag if:
        - Heading levels inconsistent for same-depth content (e.g., h2 vs h3 for equivalent sections).
        - Same functional area uses different heading text on different screens.
        Evidence needed: level mismatch or semantically different labels for same recurring section.

        ### 3.2.3 Consistent Navigation (Level AA)
        Compare nav_elements across screens within the same activity.
        Flag: recurring navigation mechanisms appear in different relative order.
        Evidence needed: nav element A before B on screen X, but after B on screen Y,
        where both screens share the same activity.

        ### 3.2.4 Consistent Identification (Level AA)
        Compare labels_map entries for elements serving same function across screens.
        Flag: identical-function components use different labels, roles, or descriptions.
        Evidence needed: same element identifier mapped to different
        contentDescription/accessibilityLabel or role across screens.

        ## OUTPUT FORMAT
        - Deduplicate: one issue per distinct inconsistency, state affected screen count.
        - `description` MUST NEVER contain UUIDs. Use readable ordinal references such as
            "Screen 1" and "Screen 2" instead.
        - Resolve every affected `snapshot_id` through the SNAPSHOT PATHS mapping.
            Set `image_url_or_path` to the single resolved path for one screen, or concatenate
            the resolved paths for N screens with `|` and no spaces. NEVER use a UUID as its
            value and NEVER invent a path that is not in the mapping.
            If an affected snapshot_id has no mapped path, do not report that issue.
        - `html_snippet` may include UUIDs and snapshot_id values. Reference every affected
            screen_id and activity_name there, and include element index, bounds, class,
            activity, and snapshot_id.
        - Use: source="llm/cross_screen_agent", tool_name="cross_screen_agent",
            page="mobile://{app_package}/{activity}".
        - Return only the Report schema with total_issues equal to issue_list length.
        - If no cross-screen violations found, return empty issue_list with total_issues=0.

        ## SNAPSHOT PATHS
        {json.dumps(snapshot_paths, ensure_ascii=False)}

        Screen summaries:
        {json.dumps(summaries, ensure_ascii=False)}
    """


def _screen_summaries(tool_context: ToolContext) -> list[dict[str, Any]]:
    state = tool_context.state
    summaries = state.get(MobileContextKey.CROSS_SCREEN_REPORT) or state.get(
        str(MobileContextKey.CROSS_SCREEN_REPORT),
        [],
    )
    if not isinstance(summaries, list):
        return []
    return [dict(summary) for summary in summaries if isinstance(summary, Mapping)]


def _summary_snapshot_ids(summaries: list[dict[str, Any]]) -> set[str]:
    """Return the snapshot IDs represented by the supplied screen summaries."""
    return {
        str(summary.get("screen_id", "")).strip()
        for summary in summaries
        if str(summary.get("screen_id", "")).strip()
    }


def _snapshot_paths(snapshot_ids: set[str], screenshots_dir: str | Path | None) -> dict[str, str]:
    """Map known snapshot IDs to screenshot files available to the post-pass."""
    if not snapshot_ids:
        return {}

    try:
        directories = (
            [Path(screenshots_dir)]
            if screenshots_dir is not None
            else sorted(REPORTS_ROOT.glob("*/screenshots"), reverse=True)
        )
    except OSError:
        return {}

    snapshot_paths: dict[str, str] = {}
    for directory in directories:
        try:
            screenshot_files = sorted(path for path in directory.iterdir() if path.is_file())
        except OSError:
            continue
        for screenshot_path in screenshot_files:
            snapshot_id = screenshot_path.stem.rpartition("_")[2]
            if snapshot_id in snapshot_ids and snapshot_id not in snapshot_paths:
                snapshot_paths[snapshot_id] = str(screenshot_path)
    return snapshot_paths


def _issue_snapshot_ids(html_snippet: str) -> tuple[str, ...]:
    """Extract affected snapshot IDs from the technical issue field in encounter order."""
    return tuple(dict.fromkeys(SNAPSHOT_ID_PATTERN.findall(html_snippet)))


def _with_resolved_image_paths(report: Report) -> Report:
    """Replace LLM-provided image values with paths for the referenced snapshots."""
    issues = []
    for issue in report.issue_list:
        snapshot_ids = _issue_snapshot_ids(issue.html_snippet)
        snapshot_paths = _snapshot_paths(set(snapshot_ids), None)
        image_paths = [
            snapshot_paths[snapshot_id] for snapshot_id in snapshot_ids if snapshot_id in snapshot_paths
        ]
        issues.append(issue.model_copy(update={"image_url_or_path": "|".join(image_paths)}))
    return report.model_copy(update={"issue_list": issues})


def _state_text(tool_context: ToolContext, key: MobileContextKey) -> str:
    return str(tool_context.state.get(key) or tool_context.state.get(str(key)) or "unknown").strip()


def fix_cross_screen_report_scores(callback_context: CallbackContext) -> None:
    """Replace LLM-provided cross-screen scores with deterministic values."""
    state = callback_context.state
    report_value = state.get(MobileContextKey.CROSS_SCREEN_REPORT) or state.get(
        str(MobileContextKey.CROSS_SCREEN_REPORT), {}
    )
    report = (
        Report.model_validate_json(report_value)
        if isinstance(report_value, str)
        else Report.model_validate(report_value)
    )
    state[MobileContextKey.CROSS_SCREEN_REPORT] = fix_report_scores(
        _with_resolved_image_paths(report), 1, CROSS_SCREEN_RULES_BY_LEVEL
    ).model_dump(mode="json")


cross_screen_agent = LlmAgent(
    name="MobileCrossScreenAgent",
    model=MODEL,
    description="Find WCAG violations that are visible only across mobile screens.",
    instruction=get_cross_screen_instruction,
    output_schema=Report,
    output_key=MobileContextKey.CROSS_SCREEN_REPORT,
    after_agent_callback=fix_cross_screen_report_scores,
)
