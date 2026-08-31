import json
from pathlib import Path

import yaml
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, ContextKey
from schemas import Report

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "wcag_mobile.yml"


def get_mobile_static_instruction(tool_context: ToolContext) -> str:
    navigator_data = tool_context.state.get(ContextKey.MOBILE_NAVIGATOR_DATA, {})
    with PROMPT_PATH.open(encoding="utf-8") as file:
        wcag_prompt = yaml.safe_dump(yaml.safe_load(file), sort_keys=False)
    return f"""
        Analyze the Android accessibility snapshots against the supplied WCAG mobile rules.
        Report only issues supported by the snapshot data. Return only the Report schema.
        Use source "mobile-static". Put element index, bounds, class, activity, and snapshot
        position in html_snippet because they are not separate fields in the Issue schema.

        WCAG mobile rules:
        {wcag_prompt}

        Navigator data:
        {json.dumps(navigator_data, ensure_ascii=False, default=str)}
    """


init_agent = LlmAgent(
    name="MobileStaticInitAgent",
    model=MODEL,
    description="Analyze mobile snapshots against WCAG mobile rules.",
    instruction=get_mobile_static_instruction,
    output_schema=Report,
    output_key=ContextKey.MOBILE_STATIC_RESULTS,
)
