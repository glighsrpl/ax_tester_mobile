from math import hypot
from typing import Any
from xml.etree import ElementTree

from mobile_tools.base import MobileElementInfo, MobileNavigatorState
from mobile_tools.consumers.base import MobileBaseConsumer
from mobile_tools.tree import bounds_center, bounds_size, get_interactive_elements, parse_mobile_tree
from schemas import Issue, ScoreInfo
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag258"])
MIN_TARGET_SIZE = 48.0
DEFAULT_SCREEN_DENSITY = 2.75 # default value (1080p screen with 400dp width) to make the test device-independent.
MIN_SPACING = 24.0
INLINE_MAX_HEIGHT = 30.0


class TouchTargetConsumer(MobileBaseConsumer):
    name = "mobile-touch-target-consumer"
    report_key = "mobile_touch_target_report"

    def __init__(
        self,
        config: dict[str, Any] | float | None = None,
        *,
        min_size: float = MIN_TARGET_SIZE,
    ):
        if isinstance(config, int | float):
            min_size, config = float(config), None
        self.min_size = float(min_size)
        self.screen_density = float((config or {}).get("screen_density", DEFAULT_SCREEN_DENSITY))
        if self.screen_density <= 0:
            raise ValueError("screen_density must be greater than zero")
        self._issues: list[dict[str, Any]] = []
        self._checked = 0
        self._seen: set[str] = set()
        self._targets: list[tuple[MobileElementInfo, str | None, str]] = []
        self._screens: dict[str, list[MobileElementInfo]] = {}

    def consume(self, state: MobileNavigatorState, **kwargs) -> None:
        element = state.current_element
        if not element or not element.is_interactive() or not element.bounds:
            return

        key = element.get_focus_key()
        if key in self._seen:
            return
        self._seen.add(key)

        if not self._size(element):
            return

        self._checked += 1
        screen_key = state.accessibility_tree or state.page_screenshot or state.activity or "unknown"
        self._targets.append((element, state.activity, screen_key))
        peers = self._screens.get(screen_key)
        if peers is None:
            peers = []
            if state.accessibility_tree:
                try:
                    peers = get_interactive_elements(parse_mobile_tree(state.accessibility_tree))
                except ElementTree.ParseError:
                    pass
            self._screens[screen_key] = peers
        if not any(peer.get_focus_key() == key for peer in peers):
            peers.append(element)

    def finalize(self) -> dict[str, Any]:
        self._issues = []
        for element, activity, screen_key in self._targets:
            width, height = self._size(element) or (0.0, 0.0)
            if width >= self.min_size and height >= self.min_size:
                continue
            peers = self._screens[screen_key]
            if self._is_inline(element, height) or self._has_equivalent(element, peers):
                continue
            if self._has_sufficient_spacing(element, peers):
                continue
            self._issues.append(self._build_issue(element, width, height, activity))

        return {
            "name": self.name,
            "issue_list": self._issues,
            "checked": self._checked,
            "score_passed": ScoreInfo(level_AA=self._checked - len(self._issues)),
            "score_total": ScoreInfo(level_AA=self._checked),
        }

    def _build_issue(
        self,
        element: MobileElementInfo,
        width: float,
        height: float,
        activity: str | None,
    ) -> dict[str, Any]:
        label = element.get_label() or element.class_name or "interactive element"
        resolved_activity = activity or "unknown"
        severity = self._severity(min(width, height))
        issue = Issue(
            id=f"mobile-touch-target-{resolved_activity}-{element.index}",
            wcag_rule=WCAG_RULE,
            description=(
                f"Interactive element '{label}' has a touch target of {width:.1f}x{height:.1f}dp, "
                f"below the minimum {self.min_size:.0f}x{self.min_size:.0f}dp."
            ),
            severity=severity,
            source="mobile-static",
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
        ).model_dump()
        issue["activity"] = resolved_activity
        return issue

    def _size(self, element: MobileElementInfo) -> tuple[float, float] | None:
        try:
            width, height = bounds_size(element.bounds or "")
        except ValueError:
            return None
        return width / self.screen_density, height / self.screen_density

    @staticmethod
    def _is_inline(element: MobileElementInfo, height: float) -> bool:
        return "textview" in (element.class_name or "").casefold() and height < INLINE_MAX_HEIGHT

    def _has_equivalent(
        self,
        element: MobileElementInfo,
        peers: list[MobileElementInfo],
    ) -> bool:
        label = element.get_label().strip().casefold()
        if not label:
            return False
        for peer in peers:
            size = self._size(peer)
            if (
                peer.get_focus_key() != element.get_focus_key()
                and peer.get_label().strip().casefold() == label
                and size is not None
                and size[0] >= self.min_size
                and size[1] >= self.min_size
            ):
                return True
        return False

    def _has_sufficient_spacing(
        self,
        element: MobileElementInfo,
        peers: list[MobileElementInfo],
    ) -> bool:
        distances = [
            distance
            for peer in peers
            if peer.get_focus_key() != element.get_focus_key()
            and (distance := self._distance(element, peer)) is not None
        ]
        return bool(distances) and min(distances) >= MIN_SPACING

    def _distance(self, first: MobileElementInfo, second: MobileElementInfo) -> float | None:
        first_size = self._size(first)
        second_size = self._size(second)
        if first_size is None or second_size is None or not first.bounds or not second.bounds:
            return None
        first_center = bounds_center(first.bounds)
        second_center = bounds_center(second.bounds)
        horizontal = max(
            abs(first_center[0] - second_center[0]) / self.screen_density - (first_size[0] + second_size[0]) / 2,
            0.0,
        )
        vertical = max(
            abs(first_center[1] - second_center[1]) / self.screen_density - (first_size[1] + second_size[1]) / 2,
            0.0,
        )
        return hypot(horizontal, vertical)

    @staticmethod
    def _severity(size: float) -> str:
        if size >= 44:
            return "minor"
        if size >= 24:
            return "moderate"
        return "critical"
