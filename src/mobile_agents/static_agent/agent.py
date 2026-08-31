import json
from collections.abc import Mapping
from typing import Any

from google.adk.agents import SequentialAgent
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from mobile_agents.static_agent.contrast_agent import contrast_agent
from mobile_agents.static_agent.init_agent import init_agent
from schemas import Report


def get_mobile_merge_instruction(tool_context: ToolContext) -> str:
    """Build the merge prompt from the separate deterministic and LLM reports."""
    deterministic_report = _state_report(tool_context, MobileContextKey.DETERMINISTIC_REPORT)
    contrast_report = _state_report(tool_context, MobileContextKey.CONTRAST_REPORT)
    llm_report = _state_report(tool_context, MobileContextKey.LLM_REPORT)
    return f"""
        Merge the following mobile accessibility reports into a single Report schema.

        INSTRUCTIONS:

        1. For each finding, extract the values of "activity" and "bounds" from inside its html_snippet. Use these ONLY to build the identity key — never modify the snippet.

        2. Identity key = (wcag_rule, activity extracted from snippet, bounds extracted from snippet, failure type/description semantically equivalent). Two findings with the same identity key are DUPLICATES.

        3. If two or more findings share the same identity key → emit ONE issue:
        - Keep the html_snippet from the contrast agent source (it is longer and contains measurement fields). Emit it VERBATIM.
        - Set source = "both".

        4. If a finding has no duplicate → emit it unchanged with its original source value.

        5. Never modify, truncate, summarize, or reformat any html_snippet.

        6. Different wcag_rule, different activity, different bounds, or different failure type → DISTINCT issues, even if they target the same element.

        7. Source values:
        - "deterministic_analyzer" — found only by deterministic analyzer
        - "llm/contrast_agent" — found only by contrast agent
        - "llm" — found only by LLM agent
        - "both" — found by ≥ 2 agents (merged)

        8. Set total_issues = count of final unique issues.

        9. Return ONLY the Report schema. Do NOT include input reports. Do NOT discarded duplicates. 

        Deterministic report:
        {json.dumps(deterministic_report, ensure_ascii=False)}

        Contrast report:
        {json.dumps(contrast_report, ensure_ascii=False)}

        LLM report:
        {json.dumps(llm_report, ensure_ascii=False)}
    """ #FIXME: fix rule number 9


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


mobile_static_analysis_agent = SequentialAgent(
    name="MobileStaticAnalysisAgent",
    description="Run WCAG static analysis on mobile snapshots.",
    sub_agents=[contrast_agent, init_agent],
)

mobile_merge_agent = LlmAgent(
    name="MobileMergeReportsAgent",
    model=MODEL,
    description="Merge deterministic and LLM mobile accessibility reports.",
    instruction=get_mobile_merge_instruction,
    output_schema=Report,
    output_key=MobileContextKey.STATIC_RESULTS,
)
