import json
import logging
import re
from collections import Counter
from typing import Any

from common import MODEL_NAME, ContextKey
from schemas import Issue, ScoreInfo
from tools.base import ActiveElementInfo, NavigatorState
from tools.consumers.base import BaseConsumer
from utils.llm_helper import call_llm
from utils.wcag_helper import get_rule_name_from_axe_tags, get_wcag_level

logger = logging.getLogger(__name__)


WCAG_RULE_CONTEXT = get_rule_name_from_axe_tags(["wcag244"])
WCAG_RULE_LINK_ONLY = get_rule_name_from_axe_tags(["wcag249"])

LINK_PURPOSE_PROMPT = """
You are evaluating whether focused links violate WCAG link-purpose requirements.

Rules:
- WCAG 2.4.9 Link Purpose (Link Only): fail when the purpose cannot be understood from the link itself.
- WCAG 2.4.4 Link Purpose (In Context): fail when the purpose cannot be understood from the link plus its programmatically available context.

Important limitation:
- The provided evidence is limited. You have the focused link accessible name, description, href, and HTML snippet.
- You do NOT have the full surrounding paragraph/list/table context yet.
- Because of that, be conservative for WCAG 2.4.4 and only mark it as failing when the evidence is strong enough
  even without richer context.

Examples:
- "Download annual report (PDF)" -> likely pass both.
- "Read more" with no other context available -> fail 2.4.9. For 2.4.4, only fail if the evidence still makes purpose too ambiguous.
- Two links both named "Details" pointing to different hrefs -> fail 2.4.9 and usually fail 2.4.4 because the available evidence does not disambiguate them.
- A link with empty accessible name -> fail both.
- A link whose accessible name is just a raw URL -> usually fail 2.4.9 and may fail 2.4.4 if no helpful context is available.

Decision guidance:
- Use `accessible_name` and `accessible_description` as the primary signal (role will be always `link`).
- Treat generic names like "read more", "details", "click here", "learn more", "more", "open" as suspicious,
  but decide based on the actual evidence, not on a hardcoded rule alone.
- HTML snippets may help when the snippet itself contains enough text to clarify the purpose.
- If evidence is insufficient for 2.4.4, prefer not to flag 2.4.4.
- Be specific about destination purpose:
  when evaluating a link, explicitly reason about what destination page/resource the link appears to open,
  using href and available context.
- In reason_link_only and reason_in_context, mention the inferred destination
  (for example: "destination appears to be /pricing", "opens annual report PDF", "destination unclear from link text").
- If destination cannot be inferred, state that clearly.

Return JSON ONLY as an array of objects with keys:
- index: integer
- fail_link_only: boolean
- fail_in_context: boolean
- reason_link_only: string
- reason_in_context: string
- severity: one of critical, serious, moderate, minor
- confidence: one of high, medium, low
- fix: short remediation guidance
- why_this_matters: plain-language sentence describing the user impact
- potential_exposures: array of objects with category and description strings

Example output:
[
  {
    "index": 0,
    "fail_link_only": true,
    "fail_in_context": false,
    "reason_link_only": "The accessible name 'Read more' is too generic by itself.",
    "reason_in_context": "",
    "severity": "moderate",
    "confidence": "high",
    "fix": "Replace the link text with wording that identifies the destination or action.",
    "why_this_matters": "Users may not know where the link will take them before activating it.",
    "potential_exposures": [
      {
        "category": "Navigation ambiguity",
        "description": "Users may need to open the link before they can understand its purpose."
      }
    ]
  }
]
"""


class LinkPurposeConsumer(BaseConsumer):
    """Detect link purpose issues for focused link elements."""

    name = "link-purpose-consumer"
    report_key = ContextKey.LINK_PURPOSE_REPORT

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.3,
        max_items_per_batch: int = 10,
        max_prompt_chars: int = 100_000,
    ):
        self.model = model or MODEL_NAME
        self.temperature = temperature
        self.max_items_per_batch = max_items_per_batch
        self.max_prompt_chars = max_prompt_chars
        self._items: list[dict[str, Any]] = []
        self._steps = 0
        self._seen_keys: set[str] = set()

    def consume(self, state: NavigatorState, **kwargs) -> None:
        self._steps += 1

        current: ActiveElementInfo = state.cur_active_element
        if current is None:
            return

        ax_info = current.element_ax_info or {}
        role = str(ax_info.get("role") or "").strip().lower()
        if role != "link":
            return

        # check for already visited element
        dedupe_key = current.get_focus_key()
        if dedupe_key in self._seen_keys:
            return
        self._seen_keys.add(dedupe_key)

        self._items.append(
            {
                "index": self._steps - 1,
                "dedupe_key": dedupe_key,
                "backend_dom_node_id": current.backend_dom_node_id,
                "html_snippet": current.element_out_html or "",
                "href": current.element_href,
                "name": ax_info.get("name"),
                "description": ax_info.get("description"),
            }
        )

    def finalize(self) -> dict[str, Any]:
        """Run LLM analysis and build issues."""
        logger.info(f"Start finalization of {self.__class__.__name__} consumer")

        if not self._items:
            return {
                "name": self.name,
                "issue_list": [],
                "checked": 0,
                "score_passed": ScoreInfo(),
                "score_total": ScoreInfo(),
            }

        batches = self._batch_items(self._items)
        decisions: list[dict[str, Any]] = []

        for batch in batches:
            decisions.extend(self._analyze_batch(batch))

        issues = self._build_issues(self._items, decisions)

        level_counts = Counter(get_wcag_level(item.get("wcag_rule")) for item in issues)
        level_A_issues = level_counts["A"]
        level_AAA_issues = level_counts["AAA"]
        return {
            "name": self.name,
            "issue_list": issues,
            "checked": len(self._items),
            "score_passed": ScoreInfo(
                level_A=len(self._items) - level_A_issues,
                level_AAA=len(self._items) - level_AAA_issues,
            ),
            "score_total": ScoreInfo(level_A=len(self._items), level_AAA=len(self._items)),
        }

    def _batch_items(self, items: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        base_prompt_len = len(LINK_PURPOSE_PROMPT)
        current_len = base_prompt_len

        for item in items:
            item_len = self._estimate_item_prompt_len(item)
            if current and (
                len(current) == self.max_items_per_batch or current_len + item_len > self.max_prompt_chars
            ):
                batches.append(current)
                current = []
                current_len = base_prompt_len

            current.append(item)
            current_len += item_len

        if current:
            batches.append(current)

        return batches

    def _estimate_item_prompt_len(self, item: dict[str, Any]) -> int:
        return (
            sum(len(str(item.get(key) or "")) for key in ("name", "description", "href", "html_snippet")) + 200
        )

    def _analyze_batch(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages = self._build_messages(batch)
        response_text = call_llm(self.model, self.temperature, messages)
        return self._parse_response(response_text)

    def _build_messages(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        items_payload = [
            {
                "index": item["index"],
                "accessible_name": item.get("name"),
                "accessible_description": item.get("description"),
                "href": item.get("href"),
                "html_snippet": item.get("html_snippet"),
            }
            for item in batch
        ]

        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": LINK_PURPOSE_PROMPT.strip()},
                    {"type": "text", "text": json.dumps(items_payload, ensure_ascii=True, indent=2)},
                ],
            }
        ]

    def _parse_response(self, text: str) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(text)
        except Exception:
            match = re.search(r"(\[.*\])", text, re.DOTALL)
            if not match:
                return []
            try:
                parsed = json.loads(match.group(1))
            except Exception:
                return []

        if not isinstance(parsed, list):
            return []

        decisions: list[dict[str, Any]] = []
        for item in parsed:
            if not isinstance(item, dict) or "index" not in item:
                continue

            severity = str(item.get("severity") or "moderate").lower()
            if severity not in {"critical", "serious", "moderate", "minor"}:
                severity = "moderate"

            confidence = str(item.get("confidence") or "medium").lower()
            if confidence not in {"high", "medium", "low"}:
                confidence = "medium"

            decisions.append(
                {
                    "index": item.get("index"),
                    "fail_link_only": bool(item.get("fail_link_only")),
                    "fail_in_context": bool(item.get("fail_in_context")),
                    "reason_link_only": str(item.get("reason_link_only") or "").strip(),
                    "reason_in_context": str(item.get("reason_in_context") or "").strip(),
                    "severity": severity,
                    "confidence": confidence,
                    "fix": str(item.get("fix") or "").strip(),
                    "why_this_matters": str(item.get("why_this_matters") or "").strip(),
                    "potential_exposures": self._normalize_potential_exposures(item.get("potential_exposures")),
                }
            )
        return decisions

    def _normalize_potential_exposures(self, value: Any) -> list[dict[str, str]]:
        exposures: list[dict[str, str]] = []
        for exposure in value if isinstance(value, list) else []:
            if isinstance(exposure, dict):
                category = str(exposure.get("category") or "").strip()
                description = str(exposure.get("description") or "").strip()
                if category and description:
                    exposures.append({"category": category, "description": description})
        return exposures

    def _build_issues(
        self, items: list[dict[str, Any]], decisions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        by_index = {decision.get("index"): decision for decision in decisions if isinstance(decision, dict)}
        issues: list[dict[str, Any]] = []

        for item in items:
            decision = by_index.get(item.get("index"))
            if not decision:
                continue

            node_id = item.get("backend_dom_node_id") or item.get("dedupe_key") or "unknown"
            html_snippet = item.get("html_snippet") or ""
            fix = decision.get("fix") or "Use link text that clearly identifies the destination or action."
            severity = decision.get("severity") or "moderate"
            confidence = decision.get("confidence") or "medium"
            why_this_matters = (
                decision.get("why_this_matters")
                or "Users may not understand where this link will take them before activating it."
            )
            potential_exposures = decision.get("potential_exposures") or [
                {
                    "category": "Navigation ambiguity",
                    "description": "Users may need to open the link before they can understand its purpose.",
                },
                {
                    "category": "User impact",
                    "description": "Screen reader and keyboard users may have more difficulty choosing the right link.",
                },
            ]

            # 2.4.9 - Link Purpose (Link Only) (Level AAA)
            if decision.get("fail_link_only"):
                reason = decision.get("reason_link_only") or "The link purpose is not clear from the link alone."
                issues.append(
                    Issue(
                        id=f"link-purpose-link-only-{node_id}",
                        wcag_rule=WCAG_RULE_LINK_ONLY,
                        description=reason,
                        severity=severity,
                        source="llm/link_purpose_analyzer",
                        confidence=confidence,
                        html_snippet=html_snippet,
                        fix=fix,
                        image_url_or_path=None,
                        why_this_matters=why_this_matters,
                        potential_exposures=potential_exposures,
                    ).model_dump()
                )

            # 2.4.4 - Link Purpose (In Context) (Level A)
            if decision.get("fail_in_context"):
                reason = (
                    decision.get("reason_in_context")
                    or "The link purpose is not clear even with the available context."
                )
                issues.append(
                    Issue(
                        id=f"link-purpose-context-{node_id}",
                        wcag_rule=WCAG_RULE_CONTEXT,
                        description=reason,
                        severity=severity,
                        source="llm/link_purpose_analyzer",
                        confidence=confidence,
                        html_snippet=html_snippet,
                        fix=fix,
                        image_url_or_path=None,
                        why_this_matters=why_this_matters,
                        potential_exposures=potential_exposures,
                    ).model_dump()
                )

        return issues


if __name__ == "__main__":
    import asyncio
    import json
    import sys

    from tools import RuntimeNavigatorTool
    from utils.browser_session import BROWSER_SESSION

    output_dir = "results/debug"
    consumer = LinkPurposeConsumer()

    default_url = "https://shop.reply.com"
    # default_url = "https://apple.com"
    test_url = default_url if len(sys.argv) < 2 else sys.argv[1]

    async def _run() -> None:
        url = test_url if test_url.startswith(("http://", "https://")) else f"https://{test_url}"
        await BROWSER_SESSION.create_session()
        await BROWSER_SESSION.goto(url)
        try:
            result = (await RuntimeNavigatorTool({"consumers": [consumer]}).execute()).to_dict()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        finally:
            await BROWSER_SESSION.close_session()

    asyncio.run(_run())
