from collections import defaultdict
from typing import Any
from xml.etree import ElementTree

from mobile_tools.base import MobileElementInfo, MobileNavigatorState
from mobile_tools.consumers.base import MobileBaseConsumer
from mobile_tools.tree import parse_mobile_tree
from schemas import Issue, ScoreInfo
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag131", "wcag332"])
GENERIC_HINTS = {"", "enter text", "input", "type here", "...", "…"}
GENERIC_INPUT_TYPES = {"", "0", "1", "generic", "none", "normal", "text", "textnormal", "typeclasstext"}
SPECIFIC_INPUT_HINTS = (
    "address",
    "date",
    "email",
    "name",
    "number",
    "numeric",
    "password",
    "phone",
    "postal",
    "search",
    "time",
    "url",
    "username",
    "zip",
)

# TODO [Static Agent LLM]: verify label adequately describes expected input (3.3.2)
# TODO [Static Agent LLM]: detect visual layout relationships not expressed programmatically (1.3.1)


class FormLabelConsumer(MobileBaseConsumer):
    name = "mobile-form-label-consumer"
    report_key = "mobile_form_label_report"

    def __init__(self):
        self._issues: list[dict[str, Any]] = []
        self._checked = 0
        self._seen: set[str] = set()
        self._targets: list[tuple[MobileElementInfo, str, str]] = []
        self._screens: dict[str, list[MobileElementInfo]] = {}

    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        element = state.current_element
        if not element or not self._is_form_element(element):
            return

        key = element.get_focus_key()
        if key in self._seen:
            return
        self._seen.add(key)

        activity = state.activity or "unknown"
        screen_key = state.accessibility_tree or state.page_screenshot or activity
        self._targets.append((element, activity, screen_key))
        self._checked += 1

        if screen_key not in self._screens:
            try:
                self._screens[screen_key] = parse_mobile_tree(state.accessibility_tree or "")
            except ElementTree.ParseError:
                self._screens[screen_key] = []
        peers = self._screens[screen_key]
        if not any(peer.get_focus_key() == key for peer in peers):
            peers.append(element)

    def finalize(self) -> dict[str, Any]:
        self._issues = []
        failed: set[str] = set()
        grouped: dict[tuple[str, str], list[MobileElementInfo]] = defaultdict(list)

        for element, activity, screen_key in self._targets:
            class_name = (element.class_name or "").casefold()
            if "edittext" in class_name:
                violations = self._edit_violations(element, self._screens[screen_key])
                if violations:
                    failed.add(element.get_focus_key())
                for check_type in violations:
                    self._issues.append(self._build_issue(element, activity, check_type))
            elif "radiobutton" in class_name:
                grouped[(activity, f"radio:{screen_key}")].append(element)
            elif "checkbox" in class_name:
                grouped[(activity, f"checkbox:{screen_key}")].append(element)

        for (activity, _), controls in grouped.items():
            parents = {element.parent_index for element in controls}
            if len(controls) > 1 and (len(parents) != 1 or parents.pop() in {None, 0}):
                failed.update(element.get_focus_key() for element in controls)
                self._issues.append(self._build_issue(controls[0], activity, "group"))

        return {
            "name": self.name,
            "issue_list": self._issues,
            "checked": self._checked,
            "score_passed": ScoreInfo(level_A=self._checked - len(failed)),
            "score_total": ScoreInfo(level_A=self._checked),
        }

    @staticmethod
    def _is_form_element(element: MobileElementInfo) -> bool:
        class_name = (element.class_name or "").casefold()
        return any(role in class_name for role in ("edittext", "radiobutton", "checkbox"))

    def _edit_violations(
        self,
        element: MobileElementInfo,
        peers: list[MobileElementInfo],
    ) -> list[str]:
        violations = []
        if element.hint is None and not self._has_label_association(element, peers):
            violations.append("label")
        if element.hint is not None and element.hint.strip().casefold() in GENERIC_HINTS:
            violations.append("hint")
        has_visible_label = element.parent_index is not None and any(
            peer.parent_index == element.parent_index
            and "textview" in (peer.class_name or "").casefold()
            and bool((peer.text or "").strip())
            for peer in peers
        )
        if not has_visible_label:
            violations.append("visible-label")
        if not self._has_specific_input_type(element):
            violations.append("input-type")
        return violations

    @staticmethod
    def _has_label_association(
        element: MobileElementInfo,
        peers: list[MobileElementInfo],
    ) -> bool:
        if element.label_for:
            return True
        target_id = _normalize_id(element.resource_id)
        return bool(target_id) and any(_normalize_id(peer.label_for) == target_id for peer in peers)

    @staticmethod
    def _has_specific_input_type(element: MobileElementInfo) -> bool:
        if element.input_type is not None:
            normalized = "".join(character for character in element.input_type.casefold() if character.isalnum())
            return normalized not in GENERIC_INPUT_TYPES
        hints = f"{element.class_name or ''} {element.resource_id or ''}".casefold()
        return any(hint in hints for hint in SPECIFIC_INPUT_HINTS)

    def _build_issue(
        self,
        element: MobileElementInfo,
        activity: str,
        check_type: str,
    ) -> dict[str, Any]:
        details = {
            "label": (
                "serious",
                "Form input has neither a hint nor a programmatic label association.",
                "Add a meaningful hint or associate a visible label using labelFor.",
            ),
            "hint": (
                "moderate",
                "Form input uses a generic or empty hint.",
                "Replace the hint with instructions specific to the expected input.",
            ),
            "visible-label": (
                "minor",
                "Form input has no visible TextView label in the same container.",
                "Provide a persistent visible label next to the input.",
            ),
            "input-type": (
                "minor",
                "Form input does not expose a specific input type.",
                "Set an inputType that identifies the expected data format.",
            ),
            "group": (
                "moderate",
                "Related radio buttons or checkboxes have no common non-root container.",
                "Place related choices in a programmatically distinguishable group container.",
            ),
        }
        severity, description, fix = details[check_type]
        issue = Issue(
            id=f"mobile-form-{check_type}-{activity}-{element.index}",
            wcag_rule=WCAG_RULE,
            description=description,
            severity=severity,
            source="mobile-static",
            confidence="high",
            html_snippet=(
                f"class={element.class_name or '-'} resource-id={element.resource_id or '-'} "
                f"hint={element.hint if element.hint is not None else '-'} "
                f"labelFor={element.label_for or '-'} inputType={element.input_type or '-'} "
                f"parent={element.parent_index} bounds={element.bounds or '-'}"
            ),
            fix=fix,
            image_url_or_path=None,
            why_this_matters="Users need clear instructions and programmatic relationships to complete forms accurately.",
            potential_exposures=[
                {
                    "category": "Form relationships",
                    "description": "Assistive technologies may not identify an input's purpose or related choices.",
                }
            ],
        ).model_dump()
        issue["activity"] = activity
        return issue


def _normalize_id(value: str | None) -> str:
    return (value or "").strip().casefold().rsplit("/", 1)[-1]
