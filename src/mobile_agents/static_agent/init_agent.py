import json
from functools import lru_cache
from pathlib import Path

import yaml
from google.adk.agents.callback_context import CallbackContext
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from schemas import Report
from schemas.issues import fix_report_scores, xml_element_count

PROMPT_PATH = Path(__file__).resolve().parents[2] / "prompts" / "wcag_mobile.yml"


def get_mobile_static_instruction(tool_context: ToolContext) -> str:
    snapshot_data = tool_context.state.get(MobileContextKey.NAVIGATOR_DATA) or tool_context.state.get(
        str(MobileContextKey.NAVIGATOR_DATA),
        {},
    )
    platform = str(
        tool_context.state.get(MobileContextKey.PLATFORM)
        or tool_context.state.get(str(MobileContextKey.PLATFORM))
        or ""
    )
    wcag_prompt = yaml.safe_dump(_mobile_wcag_rules(platform), sort_keys=False)
    return f"""
        Analyze this accessibility snapshot against the supplied WCAG mobile rules.

        ## EVIDENCE POLICY — ZERO FALSE POSITIVES
            - Report ONLY when you have CONCRETE EVIDENCE of a violation in the snapshot data.
            - Concrete evidence = a specific element with specific attributes that directly contradict a rule's pass condition.
            - If you cannot PROVE a violation from the data → DO NOT report it.
            - When in doubt → SKIP. No guessing. No assumptions.
            - Empty issue list is a valid and expected output.

        Return only the Report schema.
        Use source "llm". Put element index, bounds, class, activity, snapshot_id, and
        the xpath or resource-id when available in html_snippet because they are not
        separate fields in the Issue schema.
        The tested platform is {platform}. Apply common fixes only as remediation
        guidance.

        WCAG mobile rules:
        {wcag_prompt}

        Snapshot data:
        {json.dumps(snapshot_data, ensure_ascii=False, default=str)}
    """


def _mobile_wcag_rules(platform: str = "") -> list[dict[str, object]]:
    prompt = _mobile_prompt()
    criteria_by_level = prompt.get("levels", {})
    if not isinstance(criteria_by_level, dict):
        return []

    return [
        _compact_criterion(criterion, platform)
        for level, rules in criteria_by_level.items()
        if isinstance(rules, dict)
        for criterion in rules.get("success_criteria", [])
        if isinstance(criterion, dict) and criterion.get("level") == level
    ]


@lru_cache(maxsize=1)
def _mobile_prompt() -> dict[str, object]:
    with PROMPT_PATH.open(encoding="utf-8") as file:
        prompt = yaml.safe_load(file) or {}
    return prompt if isinstance(prompt, dict) else {}


def mobile_rules_by_level() -> dict[str, int]:
    """Count the WCAG criteria loaded from the mobile prompt once per process."""
    criteria_by_level = _mobile_prompt().get("levels", {})
    if not isinstance(criteria_by_level, dict):
        return {"A": 0, "AA": 0, "AAA": 0}
    return {
        level: len(rules.get("success_criteria", [])) if isinstance(rules, dict) else 0
        for level in ("A", "AA", "AAA")
        for rules in (criteria_by_level.get(level, {}),)
    }


def fix_init_report_scores(callback_context: CallbackContext) -> None:
    """Replace LLM-provided initial-analysis scores with deterministic values."""
    state = callback_context.state
    report_value = state.get(MobileContextKey.STATIC_RESULTS) or state.get(
        str(MobileContextKey.STATIC_RESULTS), {}
    )
    report = (
        Report.model_validate_json(report_value)
        if isinstance(report_value, str)
        else Report.model_validate(report_value)
    )
    snapshot_data = state.get(MobileContextKey.NAVIGATOR_DATA) or state.get(
        str(MobileContextKey.NAVIGATOR_DATA), {}
    )
    state[MobileContextKey.STATIC_RESULTS] = fix_report_scores(
        report, xml_element_count(snapshot_data), mobile_rules_by_level()
    ).model_dump(mode="json")


init_agent = LlmAgent(
    name="MobileStaticInitAgent",
    model=MODEL,
    description="Analyze mobile snapshots against WCAG mobile rules.",
    instruction=get_mobile_static_instruction,
    output_schema=Report,
    output_key=MobileContextKey.STATIC_RESULTS,
    after_agent_callback=fix_init_report_scores,
)


def _compact_criterion(criterion: object, platform: str) -> dict[str, object]:
    if not isinstance(criterion, dict):
        return {}
    return {
        "id": criterion.get("id"),
        "title": criterion.get("title"),
        "level": criterion.get("level"),
        "rule": _compact_text(criterion.get("description")),
        "mobile_note": _compact_text(criterion.get("mobile_note")),
        "common_fixes": _platform_common_fixes(criterion.get("common_fixes"), platform),
        "examples": _platform_examples(criterion.get("examples")),
    }


def _platform_common_fixes(common_fixes: object, platform: str) -> list[dict[str, object]]:
    if not isinstance(common_fixes, list):
        return []

    included_platforms = {platform, "Flutter"}
    return [fix for fix in common_fixes if isinstance(fix, dict) and fix.get("platform") in included_platforms]


def _platform_examples(examples: object) -> list[dict[str, object]]:
    if not isinstance(examples, list):
        return []
    return [example for example in examples if isinstance(example, dict)]


def _compact_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    return " ".join(value.split()) or None
