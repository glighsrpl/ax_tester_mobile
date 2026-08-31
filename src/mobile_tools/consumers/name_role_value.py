from typing import Any

from mobile_tools.base import MobileElementInfo, MobileNavigatorState
from mobile_tools.consumers.base import MobileBaseConsumer
from schemas import Issue, ScoreInfo
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag412"])
GENERIC_NAMES = {"button", "image", "icon", "img", "click", "tap", "view", "item"}
CONTAINER_ROLES = {"view", "framelayout", "linearlayout"}
STATE_ROLES = ("checkbox", "switch", "togglebutton", "radiobutton")
VALUE_ROLES = ("seekbar", "ratingbar", "progressbar")


class NameRoleValueConsumer(MobileBaseConsumer):
    name = "mobile-name-role-value-consumer"
    report_key = "mobile_name_role_value_report"

    def __init__(self):
        self._issues: list[dict[str, Any]] = []
        self._checked = 0
        self._seen: set[str] = set()
        self._failed: set[str] = set()

    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        element = state.current_element
        if not element or not element.is_interactive():
            return

        key = element.get_focus_key()
        if key in self._seen:
            return
        self._seen.add(key)

        self._checked += 1
        violations = self._get_violations(element)
        if violations:
            self._failed.add(key)
        for check_type in violations:
            self._issues.append(self._build_issue(element, state.activity, check_type))

    def finalize(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "issue_list": self._issues,
            "checked": self._checked,
            "score_passed": ScoreInfo(level_A=self._checked - len(self._failed)),
            "score_total": ScoreInfo(level_A=self._checked),
        }

    @staticmethod
    def _get_violations(element: MobileElementInfo) -> list[str]:
        violations = []
        names = [value.strip() for value in (element.text, element.content_desc) if value]
        if not any(len(name) > 1 and name.casefold() not in GENERIC_NAMES for name in names):
            violations.append("name")

        class_name = (element.class_name or "").casefold()
        simple_class = class_name.rsplit(".", 1)[-1]
        if element.clickable and simple_class in CONTAINER_ROLES:
            violations.append("role")

        needs_checked = any(role in class_name for role in STATE_ROLES)
        needs_expanded = "expandable" in class_name or "accordion" in class_name
        if (needs_checked and element.checked is None) or (needs_expanded and element.expanded is None):
            violations.append("state")

        if any(role in class_name for role in VALUE_ROLES) and not any(names):
            violations.append("value")
        return violations

    def _build_issue(
        self,
        element: MobileElementInfo,
        activity: str | None,
        check_type: str,
    ) -> dict[str, Any]:
        label = element.resource_id or element.class_name or "interactive element"
        resolved_activity = activity or "unknown"
        details = {
            "name": (
                f"Interactive element '{label}' has no meaningful accessible name.",
                "serious",
                "Add meaningful visible text or a content description that describes the control purpose.",
                "Missing accessible name",
                "Assistive technologies may announce the control without a useful name.",
            ),
            "role": (
                f"Clickable element '{label}' uses a non-semantic container class.",
                "moderate",
                "Use a semantic control class such as Button or ImageButton that exposes the correct role.",
                "Incorrect role",
                "Assistive technologies may not identify the element as an actionable control.",
            ),
            "state": (
                f"State-bearing element '{label}' does not expose its current state.",
                "moderate",
                "Expose the control's checked or expanded state through its accessibility properties.",
                "Missing state",
                "Users may not know whether the control is checked, selected, expanded, or collapsed.",
            ),
            "value": (
                f"Value-bearing element '{label}' does not expose its current value.",
                "moderate",
                "Expose the current value through visible text or a content description.",
                "Missing value",
                "Assistive technologies may announce the control without its current value.",
            ),
        }
        description, severity, fix, category, exposure = details[check_type]
        issue = Issue(
            id=f"mobile-412-{check_type}-{resolved_activity}-{element.index}",
            wcag_rule=WCAG_RULE,
            description=description,
            severity=severity,
            source="mobile-static",
            confidence="high",
            html_snippet=(
                f"class={element.class_name or '-'} resource-id={element.resource_id or '-'} "
                f"text={element.text or '-'} content-desc={element.content_desc or '-'} "
                f"enabled={element.enabled} checked={element.checked} expanded={element.expanded} "
                f"bounds={element.bounds or '-'}"
            ),
            fix=fix,
            image_url_or_path=None,
            why_this_matters="Screen reader users need an accurate name, role, state, and value to operate controls.",
            potential_exposures=[
                {
                    "category": category,
                    "description": exposure,
                }
            ],
        ).model_dump()
        issue["activity"] = resolved_activity
        return issue
