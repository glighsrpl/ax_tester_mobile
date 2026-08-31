from mobile_agents.static_agent.consumers.base import BaseConsumer
from mobile_tools.base import MobileElementInfo
from mobile_tools.tree import bounds_size
from schemas import Issue
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag258"])
MIN_TARGET_SIZE = 48.0
DEFAULT_SCREEN_DENSITY = (
    2.75  # conversion factor from pixels to dp for a 1080x1920 screen with 400dpi (standard)
)
INLINE_MAX_HEIGHT = 30.0


class TouchTargetConsumer(BaseConsumer):
    name = "mobile-touch-target-consumer"
    report_key = "mobile_touch_target_report"

    def __init__(self) -> None:
        self.min_size = MIN_TARGET_SIZE
        self.screen_density = DEFAULT_SCREEN_DENSITY

    def consume(self, element: MobileElementInfo) -> list[Issue]:
        if not element.is_interactive() or not element.bounds:
            return []
        size = self._size(element)
        if size is None:
            return []
        width, height = size
        if width >= self.min_size and height >= self.min_size:
            return []
        if self._is_inline(element, height):
            return []
        return [self._build_issue(element, width, height)]

    def _build_issue(
        self,
        element: MobileElementInfo,
        width: float,
        height: float,
    ) -> Issue:
        label = element.get_label() or element.class_name or "interactive element"
        severity = self._severity(min(width, height))
        return Issue(
            id=f"mobile-touch-target-{element.index}",
            wcag_rule=WCAG_RULE,
            description=(
                f"Interactive element '{label}' has a touch target of {width:.1f}x{height:.1f}dp, "
                f"below the minimum {self.min_size:.0f}x{self.min_size:.0f}dp."
            ),
            severity=severity,
            source="deterministic_analyzer",
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
        )

    def _size(self, element: MobileElementInfo) -> tuple[float, float] | None:
        try:
            width, height = bounds_size(element.bounds or "")
        except ValueError:
            return None
        return width / self.screen_density, height / self.screen_density

    @staticmethod
    def _is_inline(element: MobileElementInfo, height: float) -> bool:
        # Exclude inline text elements that are smaller than the minimum size but are not expected to be interactive targets.
        return "textview" in (element.class_name or "").casefold() and height < INLINE_MAX_HEIGHT

    @staticmethod
    def _severity(size: float) -> str:
        if size >= 44:
            return "minor"
        if size >= 24:
            return "moderate"
        return "critical"
