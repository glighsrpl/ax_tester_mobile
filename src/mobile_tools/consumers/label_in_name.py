import unicodedata
from typing import Any

from mobile_tools.base import MobileElementInfo, MobileNavigatorState
from mobile_tools.consumers.base import MobileBaseConsumer
from schemas import Issue, ScoreInfo
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag253"])


class LabelInNameConsumer(MobileBaseConsumer):
    """Check that an interactive control's accessible name contains its visible label."""

    name = "mobile-label-in-name-consumer"
    report_key = "mobile_label_in_name_report"

    def __init__(self) -> None:
        self._issues: list[dict[str, Any]] = []
        self._checked = 0
        self._seen: set[str] = set()

    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        element = state.current_element
        if not element or not element.is_interactive():
            return

        visible_label = _normalize(element.text)
        if not visible_label or not any(character.isalnum() for character in visible_label):
            return

        key = element.get_focus_key()
        if key in self._seen:
            return
        self._seen.add(key)
        self._checked += 1

        # Android normally exposes visible text as the accessible name when no
        # content description overrides it.
        accessible_name = _normalize(element.content_desc or element.text)
        if visible_label not in accessible_name:
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
    def _build_issue(element: MobileElementInfo, activity: str | None) -> dict[str, Any]:
        resolved_activity = activity or "unknown"
        issue = Issue(
            id=f"mobile-253-label-in-name-{resolved_activity}-{element.index}",
            wcag_rule=WCAG_RULE,
            description=(
                f"Interactive element with visible label '{element.text}' has accessible name "
                f"'{element.content_desc}' that does not contain the visible label."
            ),
            severity="serious",
            source="mobile-static",
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
        ).model_dump()
        issue["activity"] = resolved_activity
        return issue


def _normalize(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    normalized = "".join(
        " " if unicodedata.category(character).startswith(("P", "Z")) else character for character in text
    )
    return " ".join(normalized.split())
