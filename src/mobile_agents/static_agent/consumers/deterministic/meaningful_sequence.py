"""Deterministic check for WCAG 1.3.2 meaningful sequence."""

from mobile_agents.static_agent.consumers.base import BaseSnapshotConsumer
from schemas import Issue
from tools.base import MobileElementInfo
from tools.mobile_screen_scanner import MobileScanSnapshot
from tools.mobile_tree import BOUNDS_RE
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag132"])
SIGNIFICANT_VERTICAL_GAP_PX = 48


class MeaningfulSequenceConsumer(BaseSnapshotConsumer):
    """Identify tree-order pairs that are substantially reversed on screen."""

    name = "mobile-meaningful-sequence-consumer"
    report_key = "mobile_meaningful_sequence_report"

    def consume(self, snapshot: MobileScanSnapshot) -> list[Issue]:
        elements = _accessible_elements_with_valid_bounds(snapshot)
        tree_order = sorted(elements, key=lambda element: element.index)
        visual_order = sorted(elements, key=_visual_position)
        visual_positions = {element.index: position for position, element in enumerate(visual_order)}
        return [
            _build_issue(first_element, second_element)
            for first_element, second_element in zip(tree_order, tree_order[1:], strict=False)
            if _is_significant_vertical_inversion(first_element, second_element, visual_positions)
        ]


def _accessible_elements_with_valid_bounds(snapshot: MobileScanSnapshot) -> list[MobileElementInfo]:
    valid_elements: list[MobileElementInfo] = []
    for element in snapshot.elements:
        if _is_ignored_for_accessibility(element) or not element.bounds:
            continue
        if BOUNDS_RE.fullmatch(element.bounds.strip()) is None:
            continue
        valid_elements.append(element)
    return valid_elements


def _is_ignored_for_accessibility(element: MobileElementInfo) -> bool:
    return (element.important_for_accessibility or "").strip().casefold() == "no"


def _visual_position(element: MobileElementInfo) -> tuple[int, int]:
    left, top = _bounds_top_left(element)
    return top, left


def _is_significant_vertical_inversion(
    first_element: MobileElementInfo,
    second_element: MobileElementInfo,
    visual_positions: dict[int, int],
) -> bool:
    _, first_top = _bounds_top_left(first_element)
    _, second_top = _bounds_top_left(second_element)
    return (
        visual_positions[first_element.index] > visual_positions[second_element.index]
        and first_top - second_top >= SIGNIFICANT_VERTICAL_GAP_PX
    )


def _bounds_top_left(element: MobileElementInfo) -> tuple[int, int]:
    match = BOUNDS_RE.fullmatch(element.bounds or "")
    if match is None:
        raise ValueError(f"Invalid mobile bounds: {element.bounds!r}")
    left, top, _, _ = map(int, match.groups())
    return left, top


def _build_issue(first_element: MobileElementInfo, second_element: MobileElementInfo) -> Issue:
    return Issue(
        id=f"mobile-132-sequence-{first_element.index}-{second_element.index}",
        wcag_rule=WCAG_RULE,
        description=(
            "Accessibility tree order places an element substantially below the following element in visual order."
        ),
        severity="moderate",
        source="deterministic_analyzer",
        confidence="medium",
        html_snippet=(
            f"first_index={first_element.index} first_bounds={first_element.bounds}; "
            f"second_index={second_element.index} second_bounds={second_element.bounds}"
        ),
        fix="Arrange accessibility tree order to match the intended visual reading order.",
        image_url_or_path=None,
        why_this_matters="Screen reader users may encounter content in an order that changes its meaning.",
        potential_exposures=[
            {
                "category": "Reading order",
                "description": "Assistive technologies may announce content in a sequence that differs from the screen.",
            }
        ],
    )
