from mobile_agents.static_agent.consumers.base import BaseConsumer
from mobile_tools.base import MobileElementInfo
from schemas import Issue
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


class FormLabelConsumer(BaseConsumer):
    name = "mobile-form-label-consumer"
    report_key = "mobile_form_label_report"

    def consume(self, element: MobileElementInfo) -> list[Issue]:
        if "edittext" not in (element.class_name or "").casefold():
            return []
        violations = self._edit_violations(element)
        return [self._build_issue(element, check_type) for check_type in violations]

    def _edit_violations(self, element: MobileElementInfo) -> list[str]:
        violations = []
        if element.hint is None and not element.label_for:
            violations.append("label")
        if element.hint is not None and element.hint.strip().casefold() in GENERIC_HINTS:
            violations.append("hint")
        if not self._has_specific_input_type(element):
            violations.append("input-type")
        return violations

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
        check_type: str,
    ) -> Issue:
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
            "input-type": (
                "minor",
                "Form input does not expose a specific input type.",
                "Set an inputType that identifies the expected data format.",
            ),
        }
        severity, description, fix = details[check_type]
        return Issue(
            id=f"mobile-form-{check_type}-{element.index}",
            wcag_rule=WCAG_RULE,
            description=description,
            severity=severity,
            source="deterministic",
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
        )
