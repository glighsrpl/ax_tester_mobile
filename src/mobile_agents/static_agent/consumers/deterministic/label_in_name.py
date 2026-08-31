import unicodedata

from mobile_agents.static_agent.consumers.base import BaseConsumer
from schemas import Issue
from tools.mobile_base import MobileElementInfo
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag253"])


class LabelInNameConsumer(BaseConsumer):
    """Check that an interactive control's accessible name contains its visible label."""

    name = "mobile-label-in-name-consumer"
    report_key = "mobile_label_in_name_report"

    def consume(self, element: MobileElementInfo) -> list[Issue]:
        if not element.is_interactive():
            return []

        visible_label = _normalize(element.text)
        if not visible_label or not any(character.isalnum() for character in visible_label):
            return []

        # Android normally exposes visible text as the accessible name when no
        # content description overrides it.
        accessible_name = _normalize(element.content_desc or element.text)
        if visible_label not in accessible_name:
            return [self._build_issue(element)]
        return []

    @staticmethod
    def _build_issue(element: MobileElementInfo) -> Issue:
        return Issue(
            id=f"mobile-253-label-in-name-{element.index}",
            wcag_rule=WCAG_RULE,
            description=(
                f"Interactive element with visible label '{element.text}' has accessible name "
                f"'{element.content_desc}' that does not contain the visible label."
            ),
            severity="serious",
            source="deterministic_analyzer",
            confidence="high",
            html_snippet=(
                f"class={element.class_name or '-'} resource-id={element.resource_id or '-'} "
                f"text={element.text or '-'} content-desc={element.content_desc or '-'} "
                f"bounds={element.bounds or '-'}"
            ),
            fix="Include the complete visible label text in the control's accessible name, preferably at the start.",
            image_url_or_path=None,
            why_this_matters=(
                "Speech-input users need the words shown on screen to activate the same control by voice."
            ),
            potential_exposures=[
                {
                    "category": "Voice control",
                    "description": "Speaking the visible label may not activate or focus the intended control.",
                }
            ],
        )


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = "".join(
        " " if unicodedata.category(character).startswith(("P", "Z")) else character for character in text
    )
    return " ".join(normalized.split())
