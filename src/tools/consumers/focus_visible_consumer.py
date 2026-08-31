import json
import logging
import re
from typing import Any

from common import MODEL_NAME, ContextKey
from schemas import Issue, ScoreInfo
from tools.base import ActiveElementInfo, NavigatorState
from tools.consumers.base import BaseConsumer
from utils.llm_helper import call_llm
from utils.wcag_helper import get_rule_name_from_axe_tags

logger = logging.getLogger(__name__)

WCAG_RULE = get_rule_name_from_axe_tags(["wcag247"])

FOCUS_VISIBILITY_PROMPT = """
    You check keyboard focus visibility for all focused interactive elements.
    Each screenshot is centered on the focused element or may be not, if the element is on the border of the web page.
    For each item you also receive AX info (role/name/states/properties) as additional context.
    Decide for each item:
    - has_focus_indicator: true if a clear focus outline/border/box/glow surrounds the focused element. It's also ok if the background of the element changes color. Any type of highlighting is considered as a focus
    - Use screenshot as primary evidence and AX info only as supporting context.
    Return JSON ONLY as an array of objects with keys: index, has_focus_indicator.
    If unsure, set has_focus_indicator false.
    The index must match the number shown in the input label "Item {index}".
    Do not add extra keys or commentary. Use valid JSON with double quotes.

    Example output:
    [
        {"index": 0, "has_focus_indicator": true},
        {"index": 1, "has_focus_indicator": false}
    ]
"""


class FocusVisibleConsumer(BaseConsumer):
    """Analyze focus visibility using navigator states."""

    name = "focus-visible-consumer"
    report_key = ContextKey.FOCUS_VISIBLE_REPORT

    def __init__(
        self,
        model: str | None = None,
        temperature: float = 0.0,
        max_items_per_batch: int = 10,
        max_prompt_chars: int = 100_000,
    ):
        self.model = model or MODEL_NAME
        self.temperature = temperature
        self.max_items_per_batch = max_items_per_batch
        self.max_prompt_chars = max_prompt_chars
        self._items: list[dict[str, Any]] = []
        self._steps = 0
        self._seen_ids: set[int] = set()

    def consume(self, state: NavigatorState, **kwargs) -> None:
        """Collect screenshot data from the current state."""
        self._steps += 1
        current: ActiveElementInfo | None = state.cur_active_element
        if not current or not current.element_screenshot or current.element_html_tag.lower() == "body":
            return

        backend_id = current.backend_dom_node_id
        if backend_id is not None:
            if backend_id in self._seen_ids:
                return
            self._seen_ids.add(backend_id)

        self._items.append(
            {
                "index": self._steps - 1,
                "backend_dom_node_id": backend_id,
                "mime": "image/png",
                "b64": current.element_screenshot,
                "ax_info": current.element_ax_info or {},
                "html_snippet": current.element_out_html or "",
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

        batches = self._batch_items(self._items, self.max_items_per_batch, self.max_prompt_chars)
        results: list[dict[str, Any]] = []
        for batch in batches:
            results.extend(self._analyze_batch(batch))

        issues = self._build_issues(self._items, results)
        return {
            "name": self.name,
            "issue_list": issues,
            "checked": len(self._items),
            "score_passed": ScoreInfo(level_AA=len(self._items) - len(issues)),
            "score_total": ScoreInfo(level_AA=len(self._items)),
        }

    def _batch_items(
        self, items: list[dict[str, Any]], max_items_per_batch: int, max_prompt_chars: int
    ) -> list[list[dict[str, Any]]]:
        if max_items_per_batch <= 0:
            max_items_per_batch = len(items) or 1

        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        base_prompt_len = len(FOCUS_VISIBILITY_PROMPT)
        current_len = base_prompt_len

        for item in items:
            item_len = self._estimate_item_prompt_len(item)
            if current and (len(current) == max_items_per_batch or current_len + item_len > max_prompt_chars):
                batches.append(current)
                current = []
                current_len = base_prompt_len

            current.append(item)
            current_len += item_len

        if current:
            batches.append(current)

        return batches

    def _estimate_item_prompt_len(self, item: dict[str, Any]) -> int:
        ax_info_len = len(self._serialize_ax_info(item))
        return len(item.get("b64") or "") + ax_info_len + 250

    def _analyze_batch(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages = self._build_messages(batch)
        response_text = call_llm(self.model, self.temperature, messages)
        return self._parse_response(response_text)

    def _build_messages(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": FOCUS_VISIBILITY_PROMPT.strip()}]
        for item in batch:
            label = f"Item {item['index']}"
            content.append({"type": "text", "text": label})
            content.append(
                {
                    "type": "text",
                    "text": f"AX info for item {item['index']}: {self._serialize_ax_info(item)}",
                }
            )
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{item['mime']};base64,{item['b64']}"},
                }
            )
        return [{"role": "user", "content": content}]

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

        if isinstance(parsed, list):
            normalized: list[dict[str, Any]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                if "index" not in item or "has_focus_indicator" not in item:
                    continue
                parsed_indicator = self._parse_bool(item.get("has_focus_indicator"))
                if parsed_indicator is None:
                    continue
                normalized.append(
                    {
                        "index": item.get("index"),
                        "has_focus_indicator": parsed_indicator,
                    }
                )
            if normalized:
                return normalized
        return []

    def _serialize_ax_info(self, item: dict[str, Any]) -> str:
        """Safely serialize AX info for inclusion in prompts."""
        try:
            return json.dumps(item.get("ax_info") or {}, ensure_ascii=False, default=str)
        except Exception:
            return "{}"

    def _parse_bool(self, value: Any) -> bool | None:
        """Parse boolean-like values from LLM output safely."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
        return None

    def _build_issues(self, items: list[dict[str, Any]], results: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_index = {r.get("index"): r for r in results if isinstance(r, dict)}
        issues: list[dict[str, Any]] = []
        for item in items:
            res = by_index.get(item.get("index"))
            if not res:
                continue
            if not res.get("has_focus_indicator"):
                index = item.get("index")
                issue = Issue(
                    id=f"focus-visible-{index}",
                    wcag_rule=WCAG_RULE,
                    description="Focused element lacks a visible focus indicator",
                    html_snippet=item.get("html_snippet", ""),
                    severity="serious",
                    confidence="high",
                    source="llm/focus_visible_analyzer",
                    fix="Ensure all focused interactive elements display a clear, visible focus outline or border.",
                    image_url_or_path=None,
                    why_this_matters=(
                        "Keyboard users may lose track of where they are on the page and abandon the flow."
                    ),
                    potential_exposures=[
                        {
                            "category": "User impact",
                            "description": "People navigating by keyboard may not know which control is currently active.",
                        },
                    ],
                ).model_dump()
                issues.append(issue)
        return issues
