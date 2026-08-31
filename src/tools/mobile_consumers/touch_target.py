from typing import Any

from schemas import Issue, ScoreInfo
from tools.mobile_base import MobileElementInfo, MobileNavigatorState
from tools.mobile_consumers.base import MobileBaseConsumer
from tools.mobile_tree import bounds_size
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag258"])
MIN_TARGET_SIZE = 48


class TouchTargetConsumer(MobileBaseConsumer):  # FIXME
    name = "mobile-touch-target-consumer"
    report_key = "mobile_touch_target_report"

    def __init__(self, min_size: int = MIN_TARGET_SIZE):
        self.min_size = min_size
        self._issues: list[dict[str, Any]] = []
        self._checked = 0
        self._seen: set[str] = set()

    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        element = state.current_element
        if not element or not element.is_interactive() or not element.bounds:
            return

        key = element.get_focus_key()
        if key in self._seen:
            return
        self._seen.add(key)

        try:
            width, height = bounds_size(element.bounds)
        except ValueError:
            return

        self._checked += 1
        if width < self.min_size or height < self.min_size:
            self._issues.append(self._build_issue(element, width, height))

    def finalize(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "issue_list": self._issues,
            "checked": self._checked,
            "score_passed": ScoreInfo(level_AA=self._checked - len(self._issues)),
            "score_total": ScoreInfo(level_AA=self._checked),
        }

    def _build_issue(self, element: MobileElementInfo, width: int, height: int) -> dict[str, Any]:
        label = element.get_label() or element.class_name or "interactive element"
        return Issue(
            id=f"mobile-touch-target-{element.screen_id}-{element.index}",
            wcag_rule=WCAG_RULE,
            description=(
                f"Interactive element '{label}' has a touch target of {width}x{height}, "
                f"below the minimum {self.min_size}x{self.min_size}."
            ),
            severity="moderate",
            source="mobile-static",
            confidence="high",
            html_snippet=(
                f"class={element.class_name or '-'} resource-id={element.resource_id or '-'} "
                f"text={element.text or '-'} content-desc={element.content_desc or '-'} bounds={element.bounds or '-'}"
            ),
            fix="Increase the tappable area or spacing so the target is large enough for touch interaction.",
            image_url_or_path=None,
            why_this_matters="Small touch targets are harder to activate accurately, especially for users with motor impairments.",
            potential_exposures=[
                {
                    "category": "Touch accuracy",
                    "description": "Users may accidentally activate nearby controls or fail to activate this control.",
                }
            ],
        ).model_dump()
