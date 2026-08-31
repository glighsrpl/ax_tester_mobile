import re
from typing import Any
from xml.etree import ElementTree

from mobile_tools.base import MobileNavigatorState
from mobile_tools.consumers.base import MobileBaseConsumer
from schemas import Issue, ScoreInfo
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag242"])
GENERIC_TITLES = {"mainactivity", "activity", "fragment", "screen", "home"}

# TODO [Static Agent LLM]: verify title adequately describes screen content (2.4.2)
# FIXME: not used, for now; change MobileBaseConsumer with BaseConsumer from mobile_agents.static_agent.consumers.base


class PageTitleConsumer(MobileBaseConsumer):
    name = "mobile-page-title-consumer"
    report_key = "mobile_page_title_report"

    def __init__(self) -> None:
        self._issues: list[dict[str, Any]] = []
        self._checked = 0
        self._seen: set[str] = set()

    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        activity = (state.activity or "").strip()
        if activity in self._seen:
            return
        self._seen.add(activity)
        self._checked += 1

        toolbar_title, package = self._extract_tree_data(state.accessibility_tree)
        title = toolbar_title or activity
        if not title:
            self._issues.append(self._build_issue(activity, title, "missing"))
        elif self._is_generic(title, activity, package):
            self._issues.append(self._build_issue(activity, title, "generic"))

    def finalize(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "issue_list": self._issues,
            "checked": self._checked,
            "score_passed": ScoreInfo(level_A=self._checked - len(self._issues)),
            "score_total": ScoreInfo(level_A=self._checked),
        }

    @staticmethod
    def _extract_tree_data(tree_xml: str | None) -> tuple[str, str]:
        try:
            root = ElementTree.fromstring(tree_xml or "")
        except ElementTree.ParseError:
            return "", ""

        package = next((_attr(node, "package") for node in root.iter() if _attr(node, "package")), "")
        for container in root.iter():
            class_name = _attr(container, "class", "className", "type").casefold()
            if "toolbar" not in class_name and "actionbar" not in class_name:
                continue
            for child in container.iter():
                child_class = _attr(child, "class", "className", "type").casefold()
                if child is not container and "textview" in child_class:
                    title = _attr(child, "text")
                    if title:
                        return title, package
        return "", package

    @staticmethod
    def _is_generic(title: str, activity: str, package: str) -> bool:
        normalized = title.strip().casefold()
        identifiers = {
            fragment.casefold()
            for value in (activity, package)
            for fragment in re.split(r"[./:$]+", value)
            if fragment
        }
        identifiers.update(value.casefold() for value in (activity, package) if value)
        return (
            normalized in GENERIC_TITLES
            or normalized in identifiers
            or (len(normalized.split()) == 1 and len(normalized) < 3)
        )

    @staticmethod
    def _build_issue(activity: str, title: str, check_type: str) -> dict[str, Any]:
        resolved_activity = activity or "unknown"
        missing = check_type == "missing"
        issue = Issue(
            id=f"mobile-page-title-{resolved_activity}",
            wcag_rule=WCAG_RULE,
            description=(
                "Screen has no programmatically determinable title."
                if missing
                else f"Screen title '{title}' is generic and does not identify the screen purpose."
            ),
            severity="serious" if missing else "moderate",
            source="mobile-static",
            confidence="high",
            html_snippet=f"activity={resolved_activity} title={title or '-'}",
            fix="Provide a concise, descriptive title in the screen Toolbar or ActionBar.",
            image_url_or_path=None,
            why_this_matters="A descriptive title helps users understand where they are in the application.",
            potential_exposures=[
                {
                    "category": "Screen identification",
                    "description": "Users may be unable to distinguish the current screen from other screens.",
                }
            ],
        ).model_dump()
        issue["activity"] = resolved_activity
        return issue


def _attr(node: ElementTree.Element, *names: str) -> str:
    return next(((node.attrib.get(name) or "").strip() for name in names if node.attrib.get(name)), "")
