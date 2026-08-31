from mobile_agents.static_agent.consumers.base import BaseConsumer
from schemas import Issue
from tools.mobile_base import MobileElementInfo
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag111"])
IMAGE_CLASSES = ("imageview", "imagebutton")


class NonTextContentConsumer(BaseConsumer):
    """Check Android image elements for a programmatic text alternative."""

    name = "mobile-non-text-content-consumer"
    report_key = "mobile_non_text_content_report"

    def consume(self, element: MobileElementInfo) -> list[Issue]:
        if not element.is_interactive() or not self._is_image(element):
            return []
        if any((value or "").strip() for value in (element.content_desc, element.text)):
            return []
        return [self._build_issue(element)]

    @staticmethod
    def _is_image(element: MobileElementInfo) -> bool:
        class_name = (element.class_name or "").casefold()
        return any(image_class in class_name for image_class in IMAGE_CLASSES)

    @staticmethod
    def _build_issue(element: MobileElementInfo) -> Issue:
        return Issue(
            id=f"mobile-111-non-text-{element.index}",
            wcag_rule=WCAG_RULE,
            description="Interactive image has no programmatically determinable text alternative.",
            severity="serious",
            source="deterministic_analyzer",
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
        )
