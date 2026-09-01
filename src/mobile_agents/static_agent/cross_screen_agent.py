"""LLM post-pass for accessibility checks spanning multiple mobile screens."""

import json
from collections.abc import Mapping
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from schemas import Report

CROSS_SCREEN_RULES = (
    "1.3.1 - Info and Relationships (Level A)",
    "1.3.2 - Meaningful Sequence (Level A)",
    "2.4.3 - Focus Order (Level A)",
    "2.4.6 - Headings and Labels (Level AA)",
    "3.2.3 - Consistent Navigation (Level AA)",
    "3.2.4 - Consistent Identification (Level AA)",
)


def get_cross_screen_instruction(tool_context: ToolContext) -> str:
    """Build the post-pass prompt from compact screen summaries only."""
    summaries = _screen_summaries(tool_context)
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
        Two screens are comparable when they share the same activity_name OR contain
        the same recurring component pattern (e.g., same toolbar, same list structure).
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
        - Reference every affected screen_id and activity_name in html_snippet.
        - Put element index, bounds, class, activity, and snapshot_id in html_snippet.
        - Use: source="llm/cross_screen_agent", tool_name="cross_screen_agent", page="mobile".
        - No image path.
        - Return only the Report schema with total_issues equal to issue_list length.
        - If no cross-screen violations found, return empty issue_list with total_issues=0.

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


cross_screen_agent = LlmAgent(
    name="MobileCrossScreenAgent",
    model=MODEL,
    description="Find WCAG violations that are visible only across mobile screens.",
    instruction=get_cross_screen_instruction,
    output_schema=Report,
    output_key=MobileContextKey.CROSS_SCREEN_REPORT,
)
