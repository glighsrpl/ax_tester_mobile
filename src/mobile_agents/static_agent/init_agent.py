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
        Analyze this accessibility snapshot against the supplied WCAG mobile rules.

        ## EVIDENCE POLICY — ZERO FALSE POSITIVES
            - Report ONLY when you have CONCRETE EVIDENCE of a violation in the snapshot data.
            - Concrete evidence = a specific element with specific attributes that directly contradict a rule's pass condition.
            - If you cannot PROVE a violation from the data → DO NOT report it.
            - When in doubt → SKIP. No guessing. No assumptions.
            - Empty issue list is a valid and expected output.

        Return only the Report schema.
        Use source "llm". Put element index, bounds, class, activity, and snapshot_id
        in html_snippet because they are not separate fields in the Issue schema.
        Infer whether the snapshot is Android or iOS from its accessibility data and
        apply the matching platform examples; when the platform is not identifiable,
        apply only platform-agnostic requirements.

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

    if not isinstance(prompt, dict):
        return {}

    criteria_by_level = prompt.get("levels", {})
    if not isinstance(criteria_by_level, dict):
        criteria_by_level = {}

    success_criteria = [
        _compact_criterion(criterion)
        for level, rules in criteria_by_level.items()
        if isinstance(rules, dict)
        for criterion in rules.get("success_criteria", [])
        if isinstance(criterion, dict) and criterion.get("level") == level
    ]

    return {
        "wcag_version": prompt.get("wcag_version"),
        "platforms": ["Android", "iOS"],
        "levels": list(criteria_by_level),
        "success_criteria": success_criteria,
    }


def _compact_criterion(criterion: object) -> dict[str, object]:
    if not isinstance(criterion, dict):
        return {}
    return {
        "id": criterion.get("id"),
        "title": criterion.get("title"),
        "level": criterion.get("level"),
        "rule": _compact_text(criterion.get("description")),
        "mobile_note": _compact_text(criterion.get("mobile_note")),
        "examples": _compact_examples(criterion.get("examples")),
    }


def _compact_examples(examples: object) -> list[dict[str, str]]:
    if not isinstance(examples, list):
        return []

    selected_examples = _platform_examples(examples) or examples[:1]
    return [
        {
            "platform": str(example.get("context", "")),
            "example": _compact_text(example.get("description")),
        }
        for example in selected_examples[:2]
        if isinstance(example, dict)
    ]


def _platform_examples(examples: list[object]) -> list[dict[str, object]]:
    selected_examples: list[dict[str, object]] = []
    for platform in ("Android", "iOS"):
        example = next(
            (
                example
                for example in examples
                if isinstance(example, dict) and platform in str(example.get("context", ""))
            ),
            None,
        )
        if example:
            selected_examples.append(example)
    return selected_examples


def _compact_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None
