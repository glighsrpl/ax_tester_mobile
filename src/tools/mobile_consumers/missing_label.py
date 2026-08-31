from typing import Any

from schemas import Issue, ScoreInfo
from tools.mobile_base import MobileElementInfo, MobileNavigatorState
from tools.mobile_consumers.base import MobileBaseConsumer
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag412"])


class MissingLabelConsumer(MobileBaseConsumer):  # FIXME
    name = "mobile-missing-label-consumer"
    report_key = "mobile_missing_label_report"

    def __init__(self):
        self._issues: list[dict[str, Any]] = []
        self._checked = 0
        self._seen: set[str] = set()

    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        element = state.current_element
        if not element or not element.is_interactive() or not element.enabled:
            return

        key = element.get_focus_key()
        if key in self._seen:
            return
        self._seen.add(key)

        self._checked += 1
        if not (element.text or element.content_desc):
            self._issues.append(self._build_issue(element))

    def finalize(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "issue_list": self._issues,
            "checked": self._checked,
            "score_passed": ScoreInfo(level_A=self._checked - len(self._issues)),
            "score_total": ScoreInfo(level_A=self._checked),
        }

    def _build_issue(self, element: MobileElementInfo) -> dict[str, Any]:
        label = element.resource_id or element.class_name or "interactive element"
        return Issue(
            id=f"mobile-missing-label-{element.screen_id}-{element.index}",
            wcag_rule=WCAG_RULE,
            description=f"Interactive element '{label}' has no accessible text or content description.",
            severity="serious",
            source="mobile-static",
            confidence="high",
            html_snippet=(
                f"class={element.class_name or '-'} resource-id={element.resource_id or '-'} "
                f"text={element.text or '-'} content-desc={element.content_desc or '-'} bounds={element.bounds or '-'}"
            ),
            fix="Add a meaningful content description or visible text that describes the element purpose.",
            image_url_or_path=None,
            why_this_matters="Screen reader users may not understand what the control does before activating it.",
            potential_exposures=[
                {
                    "category": "Missing accessible name",
                    "description": "Assistive technologies may announce the control without a useful name.",
                }
            ],
        ).model_dump()
