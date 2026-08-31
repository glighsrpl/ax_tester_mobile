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
        Merge the following mobile accessibility reports into one Report schema.

        Preserve every supported issue. De-duplicate only issues that have the same
        WCAG rule, element evidence, and description. Preserve each issue's source:
        "deterministic" for rules-based findings, "contrast_agent" for visual findings,
        and "llm" for LLM findings.

        Deterministic report:
        {json.dumps(deterministic_report, ensure_ascii=False)}

        Contrast report:
        {json.dumps(contrast_report, ensure_ascii=False)}

        LLM report:
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
