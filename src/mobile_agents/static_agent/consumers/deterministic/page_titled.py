"""Deterministic check for WCAG 2.4.2 page titled."""

import re

from mobile_agents.static_agent.consumers.base import BaseSnapshotConsumer
from mobile_tools.screen_scanner import MobileScanSnapshot
from schemas import Issue
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag242"])
GENERIC_TITLES = {"mainactivity", "activity", "fragment", "screen"}


class PageTitledConsumer(BaseSnapshotConsumer):
    """Check that the activity title identifies the current screen."""

    name = "mobile-page-titled-consumer"
    report_key = "mobile_page_titled_report"

    def consume(self, snapshot: MobileScanSnapshot) -> list[Issue]:
        title = snapshot.activity.strip() if snapshot.activity else ""
        if title and not _is_generic_title(title):
            return []
        return [_build_issue(title)]


def _is_generic_title(title: str) -> bool:
    normalized = title.casefold()
    title_parts = [part for part in re.split(r"[./:$]+", normalized) if part]
    return normalized in GENERIC_TITLES or (title_parts and title_parts[-1] in GENERIC_TITLES)


def _build_issue(title: str) -> Issue:
    missing = not title
    return Issue(
        id=f"mobile-242-page-title-{title or 'missing'}",
        wcag_rule=WCAG_RULE,
        description=(
            "Screen activity title is missing."
            if missing
            else f"Screen activity title '{title}' is generic and does not identify the screen purpose."
        ),
        severity="serious" if missing else "moderate",
        source="deterministic",
        confidence="high",
        html_snippet=f"activity_title={title or '-'}",
        fix="Provide a concise, descriptive activity title that identifies the screen purpose.",
        image_url_or_path=None,
        why_this_matters="A descriptive title helps users understand where they are in the application.",
        potential_exposures=[
            {
                "category": "Screen identification",
                "description": "Users may be unable to distinguish the current screen from other screens.",
            }
        ],
    )
