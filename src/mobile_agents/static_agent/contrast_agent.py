"""Multimodal LLM agent for mobile screenshot contrast analysis."""

import json

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from schemas import Report


def get_contrast_instruction(tool_context: ToolContext) -> str:
    """Build the visual contrast-analysis instruction from the current snapshot."""
    snapshot_data = tool_context.state.get(MobileContextKey.NAVIGATOR_DATA) or tool_context.state.get(
        str(MobileContextKey.NAVIGATOR_DATA),
        {},
    )
    return f"""
        Analyze the attached mobile screenshot for WCAG color-contrast violations.
        The screenshot and the element bounds in the snapshot data refer to the same screen.

        Evaluate only elements with valid bounds that are fully inside the screenshot.
        Skip elements where important_for_accessibility is "no".
        Use the bounds to associate visual evidence with a specific element.

        Report text contrast failures under 1.4.3 when visual evidence shows less than
        4.5:1 for normal text, or less than 3:1 for large text (at least 18sp, or
        at least 14sp bold). If font metadata is absent, treat text as normal.
        Report UI component or meaningful graphic boundary contrast failures under
        1.4.11 when visual evidence shows less than 3:1.

        Do not estimate a ratio from an ambiguous, photographic, gradient, translucent,
        or obscured area. When contrast cannot be assessed reliably, omit the issue.
        Return only the Report schema with tool_name "contrast_agent", page set to the
        current mobile activity, and total_issues equal to issue_list length. Use source
        "contrast_agent" and confidence "medium". Include element index, bounds,
        class, activity, snapshot_id, and the observed foreground/background colors or
        visual evidence in html_snippet.

        Snapshot data:
        {json.dumps(snapshot_data, ensure_ascii=False, default=str)}
    """


contrast_agent = LlmAgent(
    name="MobileStaticContrastAgent",
    model=MODEL,
    description="Analyze mobile screenshots for WCAG contrast violations.",
    instruction=get_contrast_instruction,
    output_schema=Report,
    output_key=MobileContextKey.CONTRAST_REPORT,
)
