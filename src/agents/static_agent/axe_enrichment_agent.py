import json
import logging
import re
from collections.abc import Callable
from typing import Any

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import DUMMY_MODEL, MODEL_NAME, ContextKey
from utils.llm_helper import call_llm

logger = logging.getLogger(__name__)

DEFAULT_BATCH_SIZE = 10


class AxeIssueEnricher:
    """Add qualitative fields to axe-core issues without changing technical fields."""

    def __init__(
        self,
        *,
        model: str = MODEL_NAME,
        temperature: float = 0.0,
        batch_size: int = DEFAULT_BATCH_SIZE,
        llm_caller: Callable[[str, float, list[dict[str, Any]]], str] = call_llm,
    ) -> None:
        self.model = model
        self.temperature = temperature
        self.batch_size = max(1, batch_size)
        self.llm_caller = llm_caller

    def enrich_issues(self, issues: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
        enriched_issues = [
            {
                **issue,
                "why_this_matters": "",
                "potential_exposures": [],
            }
            for issue in issues
            if isinstance(issue, dict)
        ]
        enriched_by_id: dict[str, dict[str, Any]] = {}

        for batch in self._batches(enriched_issues):
            issue_ids = {str(issue.get("id") or "") for issue in batch}
            issue_ids.discard("")
            if not issue_ids:
                continue

            try:
                response_text = self.llm_caller(
                    self.model,
                    self.temperature,
                    self._build_messages(batch),
                )
            except Exception:
                logger.exception("Failed to enrich axe-core issue batch")
                continue

            enriched_by_id.update(self._parse_response(response_text, issue_ids))

        enriched_count = 0
        for issue in enriched_issues:
            issue_id = str(issue.get("id") or "")
            enrichment = enriched_by_id.get(issue_id)
            if enrichment:
                issue["why_this_matters"] = enrichment["why_this_matters"]
                issue["potential_exposures"] = enrichment["potential_exposures"]
                if issue["why_this_matters"] or issue["potential_exposures"]:
                    enriched_count += 1

        return enriched_issues, enriched_count

    def _batches(self, issues: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        return [issues[index : index + self.batch_size] for index in range(0, len(issues), self.batch_size)]

    def _build_messages(self, issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
        payload = [self._to_llm_payload(issue) for issue in issues]
        return [
            {
                "role": "system",
                "content": (
                    "You enrich axe-core accessibility issues for a non-technical report. "
                    "Return only valid JSON. Do not change technical issue data."
                ),
            },
            {
                "role": "user",
                "content": (
                    "For each axe-core issue, explain the impact in plain language based on the WCAG rule, "
                    "axe description, fix, and HTML snippet.\n\n"
                    "Return a JSON array. Each item must contain only:\n"
                    "- id: the exact input id\n"
                    "- why_this_matters: one concise, concrete, non-technical sentence\n"
                    "- potential_exposures: 1 to 3 objects with category and description strings\n\n"
                    "Keep categories short. Keep each exposure description to one concise sentence. "
                    "Ignore fields you are not asked to produce.\n\n"
                    f"Issues:\n{json.dumps(payload, ensure_ascii=True, indent=2)}"
                ),
            },
        ]

    def _to_llm_payload(self, issue: dict[str, Any]) -> dict[str, str]:
        return {
            "id": str(issue.get("id") or "").strip(),
            "wcag_rule": self._compact_text(issue.get("wcag_rule"), 220),
            "description": self._compact_text(issue.get("description"), 600),
            "severity": self._compact_text(issue.get("severity"), 80),
            "html_snippet": self._compact_text(issue.get("html_snippet"), 1200),
            "fix": self._compact_text(issue.get("fix"), 600),
        }

    def _parse_response(self, text: str, allowed_ids: set[str]) -> dict[str, dict[str, Any]]:
        parsed = self._load_json(text)
        if not isinstance(parsed, list):
            return {}

        enrichments: dict[str, dict[str, Any]] = {}
        for item in parsed:
            if not isinstance(item, dict):
                continue

            issue_id = str(item.get("id") or "").strip()
            if issue_id not in allowed_ids:
                continue

            why_this_matters = str(item.get("why_this_matters") or "").strip()
            potential_exposures = self._normalize_potential_exposures(item.get("potential_exposures"))
            enrichments[issue_id] = {
                "why_this_matters": why_this_matters,
                "potential_exposures": potential_exposures,
            }

        return enrichments

    def _load_json(self, text: str) -> Any:
        try:
            return json.loads(text)
        except Exception:
            match = re.search(r"(\[.*\])", text, re.DOTALL)
            if not match:
                return None
            try:
                return json.loads(match.group(1))
            except Exception:
                return None

    def _normalize_potential_exposures(self, value: Any) -> list[dict[str, str]]:
        exposures: list[dict[str, str]] = []
        for exposure in value if isinstance(value, list) else []:
            if isinstance(exposure, dict):
                category = str(exposure.get("category") or "").strip()
                description = str(exposure.get("description") or "").strip()
                if category and description:
                    exposures.append({"category": category, "description": description})
        return exposures[:3]

    def _compact_text(self, value: Any, limit: int) -> str:
        text = str(value or "").replace("\n", " ").strip()
        return text if len(text) <= limit else f"{text[: limit - 3]}..."


async def enrich_axe_report(tool_context: ToolContext) -> dict[str, Any]:
    """Enrich axe-core issues in ContextKey.AXE_REPORT with LLM qualitative fields."""
    axe_report = tool_context.state.get(ContextKey.AXE_REPORT, {})
    if not isinstance(axe_report, dict):
        logger.warning("Skipping axe issue enrichment: AXE_REPORT is not a dict")
        return {"status": "skipped", "reason": "missing_axe_report"}

    data = axe_report.get("data", {})
    if not isinstance(data, dict):
        logger.warning("Skipping axe issue enrichment: AXE_REPORT data is not a dict")
        return {"status": "skipped", "reason": "missing_axe_data"}

    issue_list = data.get("issue_list", [])
    if not isinstance(issue_list, list) or not issue_list:
        logger.info("Skipping axe issue enrichment: no axe issues found")
        return {"status": "skipped", "reason": "no_axe_issues", "total_issues": 0}

    enriched_issues, enriched_count = AxeIssueEnricher().enrich_issues(issue_list)
    updated_report = dict(axe_report)
    updated_data = dict(data)
    updated_data["issue_list"] = enriched_issues
    updated_report["data"] = updated_data
    tool_context.state[ContextKey.AXE_REPORT] = updated_report

    logger.info("axe issues enriched: %s/%s", enriched_count, len(enriched_issues))
    return {
        "status": "axe_enriched",
        "enriched_issues": enriched_count,
        "total_issues": len(enriched_issues),
        "state_key": ContextKey.AXE_REPORT,
    }


axe_enrichment_agent = LlmAgent(
    name="EnrichAxeIssuesAgent",
    model=DUMMY_MODEL,
    description="Enrich axe-core issues with qualitative report fields.",
    instruction="Call `enrich_axe_report` once and return a brief confirmation.",
    tools=[enrich_axe_report],
)
