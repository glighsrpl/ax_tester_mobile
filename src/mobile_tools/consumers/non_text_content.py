from typing import Any

from mobile_tools.base import MobileElementInfo, MobileNavigatorState
from mobile_tools.consumers.base import MobileBaseConsumer
from schemas import Issue, ScoreInfo
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag111"])
IMAGE_CLASSES = ("imageview", "imagebutton")


class NonTextContentConsumer(MobileBaseConsumer):
    """Check Android image elements for a programmatic text alternative."""

    name = "mobile-non-text-content-consumer"
    report_key = "mobile_non_text_content_report"

    def __init__(self) -> None:
        self._issues: list[dict[str, Any]] = []
        self._checked = 0
        self._seen: set[str] = set()

    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        element = state.current_element
        if not element or not element.is_interactive() or not self._is_image(element):
            return

        key = element.get_focus_key()
        if key in self._seen:
            return
        self._seen.add(key)
        self._checked += 1

        if not any((value or "").strip() for value in (element.content_desc, element.text)):
            self._issues.append(self._build_issue(element, state.activity))

    def finalize(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "issue_list": self._issues,
            "checked": self._checked,
            "score_passed": ScoreInfo(level_A=self._checked - len(self._issues)),
            "score_total": ScoreInfo(level_A=self._checked),
        }

    @staticmethod
    def _is_image(element: MobileElementInfo) -> bool:
        class_name = (element.class_name or "").casefold()
        return any(image_class in class_name for image_class in IMAGE_CLASSES)

    @staticmethod
    def _build_issue(element: MobileElementInfo, activity: str | None) -> dict[str, Any]:
        resolved_activity = activity or "unknown"
        issue = Issue(
            id=f"mobile-111-non-text-{resolved_activity}-{element.index}",
            wcag_rule=WCAG_RULE,
            description="Interactive image has no programmatically determinable text alternative.",
            severity="serious",
            source="mobile-static",
            confidence="high",
            html_snippet=(
                f"class={element.class_name or '-'} resource-id={element.resource_id or '-'} "
                f"text={element.text or '-'} content-desc={element.content_desc or '-'} "
                f"clickable={element.clickable} focusable={element.focusable} bounds={element.bounds or '-'}"
            ),
            fix=(
                "Provide a concise content description that conveys the image purpose, or explicitly remove decorative "
                "images from the accessibility tree."
            ),
            image_url_or_path=None,
            why_this_matters="Users who cannot see the image need an equivalent description of its purpose.",
            potential_exposures=[
                {
                    "category": "Missing text alternative",
                    "description": "Assistive technologies may skip the image or announce it without useful meaning.",
                }
            ],
        ).model_dump()
        issue["activity"] = resolved_activity
        return issue
