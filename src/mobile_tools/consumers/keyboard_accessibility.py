from typing import Any

from mobile_tools.base import MobileElementInfo, MobileKeyboardResult, MobileNavigatorState
from mobile_tools.consumers.base import MobileBaseConsumer
from schemas import Issue, ScoreInfo
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag211"])


class KeyboardAccessibilityConsumer(MobileBaseConsumer):
    """Report interactive elements not reached by the mobile keyboard traversal."""

    name = "mobile-keyboard-accessibility-consumer"
    report_key = "mobile_keyboard_accessibility_report"

    def __init__(self) -> None:
        self._issues: list[dict[str, Any]] = []
        self._checked = 0
        self._passed = 0
        self._seen: set[str] = set()

    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        return None

    def consume_keyboard(self, data: MobileKeyboardResult) -> None:
        for element in data.reachable:
            key = self._key(data.activity, element)
            if key in self._seen:
                continue
            self._seen.add(key)
            self._checked += 1
            self._passed += 1

        for element in data.unreachable:
            key = self._key(data.activity, element)
            if key in self._seen:
                continue
            self._seen.add(key)
            self._checked += 1
            self._issues.append(self._build_issue(element, data.activity))

    def finalize(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "issue_list": self._issues,
            "checked": self._checked,
            "score_passed": ScoreInfo(level_A=self._passed),
            "score_total": ScoreInfo(level_A=self._checked),
        }

    @staticmethod
    def _key(activity: str, element: MobileElementInfo) -> str:
        return f"{activity}:{element.get_focus_key()}"

    @staticmethod
    def _build_issue(element: MobileElementInfo, activity: str) -> dict[str, Any]:
        resolved_activity = activity or "unknown"
        label = element.get_label() or element.class_name or "interactive element"
        issue = Issue(
            id=f"mobile-211-keyboard-{resolved_activity}-{element.index}",
            wcag_rule=WCAG_RULE,
            description=f"Interactive element '{label}' was not reached during keyboard/D-pad navigation.",
            severity="serious",
            source="mobile-static",
            confidence="medium",
            html_snippet=(
                f"class={element.class_name or '-'} resource-id={element.resource_id or '-'} "
                f"text={element.text or '-'} content-desc={element.content_desc or '-'} "
                f"clickable={element.clickable} focusable={element.focusable} bounds={element.bounds or '-'}"
            ),
            fix=(
                "Ensure the control can receive focus and be operated using the platform keyboard interface, "
                "including D-pad or equivalent input."
            ),
            image_url_or_path=None,
            why_this_matters="Users who cannot use touch input need to reach and operate every control by keyboard.",
            potential_exposures=[
                {
                    "category": "Keyboard access",
                    "description": "Keyboard and switch-device users may be unable to reach this control.",
                }
            ],
        ).model_dump()
        issue["activity"] = resolved_activity
        return issue
