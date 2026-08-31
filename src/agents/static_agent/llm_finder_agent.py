import logging
from typing import Any

from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.loop_agent import LoopAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, ContextKey
from schemas import IssueList

logger = logging.getLogger(__name__)


def get_finder_instruction(tool_context: ToolContext) -> str:
    html = tool_context.state.get(ContextKey.DOM_HTML, "")
    report = tool_context.state.get(ContextKey.LOOP_REPORT, '{"issue_list": []}')
    wcag_prompt = tool_context.state.get(ContextKey.WCAG_PROMPT, "")
    checker_feedback = tool_context.state.get(ContextKey.LOOP_NOTES, "")
    logger.info(
        f"Preparing LoopFinderAgent prompt: html_chars={len(str(html))}, "
        f"wcag_prompt_chars={len(str(wcag_prompt))}, has_checker_feedback={bool(checker_feedback)}",
    )

    return (
        f"""
        You are an accessibility issue FINDER for WCAG compliance.

        WCAG 2.2 Reference:
        {wcag_prompt}

        HTML to Analyze:
        {html}

        Current Report:
        {report}

        {"Checker Feedback: " + checker_feedback if checker_feedback else ""}

        ---
        """
        + """
        TASK:
        Find NEW accessibility issues in the focused area that are NOT in current report.

        Look for:
        1. **Alt text**: Generic ("image"), missing, non-descriptive
        2. **Link text**: "click here", "read more", URLs as text
        3. **Forms**: Missing labels, placeholder-only, unclear error messages
        4. **Headings**: Skipped levels (h1→h3), vague headings, too long
        5. **Semantic**: <div> soup instead of semantic HTML, missing landmarks

        OUTPUT:
        Return ONLY JSON matching the output schema. No extra keys.
        Each issue must include:
        - id, wcag_rule, description, severity, source, confidence, html_snippet, fix, image_url_or_path
        - why_this_matters: one concise, plain-language sentence about why the issue affects users
        - potential_exposures: list of objects with category and description strings
        - Set image_url_or_path to null when not available.
        - wcag_rule must be one of the allowed values from schema; if unsure use "best-practice"
        - source must be 'llm'
        - Keep exposure categories short; keep each exposure description to one concise sentence.

        Severity: critical (blocks functionality) | serious (major impairment) | moderate (inconvenience) | minor (best practice)

        IMPORTANT:
        - Do NOT duplicate existing issues
        - Be specific in the description (counts/locations in text if needed)
        - Return ONLY the JSON object
        - Do not add extra keys beyond the schema
    """
    )


def get_checker_instruction(tool_context: ToolContext) -> str:
    html = tool_context.state.get(ContextKey.DOM_HTML, "")
    report = tool_context.state.get(ContextKey.LOOP_REPORT, '{"issue_list": []}')
    iteration = tool_context.state.get(ContextKey.LOOP_ITERATION, 0)
    logger.info(f"Preparing LoopCompletenessAgent prompt: iteration={iteration}")

    return (
        f"""
        You are a COMPLETENESS CHECKER.

        HTML to Analyze:
        {html}

        Report:
        {report}

        Iteration (1-based): {iteration}"""
        + """

        SCOPE (target coverage: 85%)
        Check these 5 areas and mark each as Covered / Not covered:
        1) Images: alt text reviewed?
        2) Links: link text / accessible name reviewed?
        3) Forms: labels + form structure reviewed?
        4) Headings: heading order/hierarchy reviewed?
        5) Semantics: landmarks / overall HTML structure reviewed?

        DECISION
        Call exit_loop() only if:
        - At least 3 iterations have completed or no more issues are found in current iteration
        - Coverage ≥ 85% (at least 4 of 5 areas covered)
        - No clear gaps (e.g., zero form review at all)

        Otherwise, if a category is clearly missing:
        - Return: "Missing: <category>"
    """
    )


def exit_loop(tool_context: ToolContext) -> dict[str, Any]:
    """Signal the loop agent to stop iterating."""
    iteration = tool_context.state.get(ContextKey.LOOP_ITERATION, 0)

    tool_context.actions.escalate = True
    tool_context.actions.skip_summarization = True
    return {"status": "complete", "iteration": iteration}


def increment_loop_iteration(callback_context: CallbackContext) -> None:
    """Increment the loop iteration before the checker builds its prompt."""
    iteration = int(callback_context.state.get(ContextKey.LOOP_ITERATION, 0) or 0)
    callback_context.state[ContextKey.LOOP_ITERATION] = iteration + 1
    logger.info(f"Incremented accessibility loop iteration to {iteration + 1}")
    return None


loop_finder_agent = LlmAgent(
    name="LoopFinderAgent",
    model=MODEL,
    instruction=get_finder_instruction,
    output_schema=IssueList,
    output_key=ContextKey.LOOP_REPORT,
)

loop_checker_agent = LlmAgent(
    name="LoopCompletenessAgent",
    model=MODEL,
    instruction=get_checker_instruction,
    tools=[exit_loop],
    output_key=ContextKey.LOOP_NOTES,
    before_agent_callback=increment_loop_iteration,
)

loop_agent = LoopAgent(
    name="AccessibilityLoopAgent",
    sub_agents=[loop_finder_agent, loop_checker_agent],
    max_iterations=5,
)
