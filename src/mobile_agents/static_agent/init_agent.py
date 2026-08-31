import json
from pathlib import Path

import yaml
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from schemas import Report

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "wcag_mobile.yml"


def get_mobile_static_instruction(tool_context: ToolContext) -> str:
    snapshot_data = tool_context.state.get(MobileContextKey.NAVIGATOR_DATA) or tool_context.state.get(
        str(MobileContextKey.NAVIGATOR_DATA),
        {},
    )
    wcag_prompt = yaml.safe_dump(_mobile_wcag_rules(), sort_keys=False)
    return f"""
        Analyze this single Android accessibility snapshot against the supplied WCAG mobile rules.
        Report only issues supported by the snapshot data. Return only the Report schema.
        Use source "llm". Put element index, bounds, class, activity, and snapshot_id
        in html_snippet because they are not separate fields in the Issue schema.
        The snapshot payload intentionally excludes screenshots; do not ask for visual evidence.

        WCAG mobile rules:
        {wcag_prompt}

        Snapshot data:
        {json.dumps(snapshot_data, ensure_ascii=False, default=str)}
    """


init_agent = LlmAgent(
    name="MobileStaticInitAgent",
    model=MODEL,
    description="Analyze mobile snapshots against WCAG mobile rules.",
    instruction=get_mobile_static_instruction,
    output_schema=Report,
    output_key=MobileContextKey.STATIC_RESULTS,
)


def _mobile_wcag_rules() -> dict[str, object]:
    with PROMPT_PATH.open(encoding="utf-8") as file:
        prompt = yaml.safe_load(file) or {}
    level_a = prompt.get("levels", {}).get("A", {}) if isinstance(prompt, dict) else {}
    criteria = level_a.get("success_criteria", []) if isinstance(level_a, dict) else []
    return {
        "wcag_version": prompt.get("wcag_version"),
        "platform": prompt.get("platform"),
        "level": "A",
        "success_criteria": [_compact_criterion(criterion) for criterion in criteria],
    }


def _compact_criterion(criterion: object) -> dict[str, object]:
    if not isinstance(criterion, dict):
        return {}
    return {
        "id": criterion.get("id"),
        "title": criterion.get("title"),
        "description": criterion.get("description"),
        "mobile_note": criterion.get("mobile_note"),
    }
