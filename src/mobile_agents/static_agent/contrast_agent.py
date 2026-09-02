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
        The screenshot, element bounds, and deterministic contrast_measurements in the
        snapshot data refer to the same screen. A measurement is the only permitted
        source of a numeric ratio: use its foreground_color, background_color, and
        contrast_ratio exactly. Do not invent or visually estimate a ratio.

        Evaluate only measured elements with valid bounds fully inside the screenshot.
        Never report an element where important_for_accessibility is "no" or enabled is
        false. Omit ambiguous, photographic, gradient, translucent, obscured, or
        otherwise unmeasurable evidence.

        ## WCAG 1.4.3 — Contrast (Minimum)
        Report only a contrast_measurement with candidate_type "text" and allowed_rule
        "1.4.3", or candidate_type "image" and allowed_rule "1.4.3_or_1.4.11" after
        the screenshot clearly shows that it is an image of text. For text use
        contrast_ratio below threshold; for an image of text use contrast_ratio below
        4.5:1 because font metadata is unavailable.
        Text and images of text have no 1.4.3 requirement when they are part of an inactive user-interface
        component, pure decoration, not visible to anyone, or part of a picture with
        significant other visual content. Use the screenshot to apply these exclusions;
        if the exception cannot be determined confidently, omit the issue. Never use
        1.4.3 for component borders, icons, or state indicators.

        ## WCAG 1.4.11 — Non-text Contrast
        Report only a contrast_measurement with candidate_type "ui_component" and
        allowed_rule "1.4.11", or candidate_type "image" and allowed_rule
        "1.4.3_or_1.4.11" after the screenshot clearly shows it is a required graphical
        object rather than an image of text, when its contrast_ratio is below 3:1.
        The failing visual information must be required to identify an active user
        interface component or its state, or be a graphical object required to
        understand content. Exclude inactive components, author-unmodified user-agent
        appearance, and graphics whose particular presentation is essential. Never use
        1.4.11 for normal text or images of text.

        Each issue must be assigned exactly one rule according to candidate_type:
        text -> 1.4.3; ui_component -> 1.4.11; image -> 1.4.3 only when it is an
        image of text, otherwise 1.4.11 only when it is a required graphical object.
        In html_snippet include
        element_index, bounds, class, activity, snapshot_id, candidate_type,
        allowed_rule, contrast_ratio, threshold, foreground_color, background_color,
        and a concise reason the element is subject to that rule.

        Return only the Report schema with tool_name "contrast_agent", page set to the
        current mobile activity, and total_issues equal to issue_list length. Use source
        "llm/contrast_agent" and confidence "medium". Include element index, bounds,
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
