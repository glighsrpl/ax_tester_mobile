import logging
import re
from typing import Any

from mobile_tools.action_executor import MobileActionExecutor, MobileTapAction, PositionHint
from tools.base import Tool, ToolResult, ToolStatus

TAP_RE = re.compile(
    r"(?:clicca|click|tap|apri|open|vai su|go to)\s+(?:su\s+)?[\"'“”]?([^\"'“”.,;\n]+)", re.I
)  # TODO: improve regex to handle more variations and languages
HINTS: dict[str, PositionHint] = {
    "in basso a destra": "bottom_right",
    "bottom right": "bottom_right",
    "in basso a sinistra": "bottom_left",
    "bottom left": "bottom_left",
    "in alto a destra": "top_right",
    "top right": "top_right",
    "in alto a sinistra": "top_left",
    "top left": "top_left",
}
IGNORED_TARGETS = {"app", "applicazione", "application"}
logger = logging.getLogger(__name__)


class MobileGuidedNavigatorTool(Tool):
    """TODO
    A tool for executing guided navigation on a mobile device based on provided instructions.
    It interprets the instructions to identify tap actions and their corresponding targets, and executes these actions on the mobile device using the MOBILE_SESSION.
    The tool can be configured with a maximum number of steps.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.max_steps = int(self.config.get("max_steps", 10))

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:  # TODO: make it more robust
            instructions = str(kwargs.get("instructions") or self.config.get("instructions") or "")
            max_steps = int(kwargs.get("max_steps", self.max_steps))
            actions = _parse_actions(instructions)[:max_steps]
            executor = MobileActionExecutor()
            return ToolResult(
                "mobile-guided-navigator",
                ToolStatus.SUCCESS,
                {"path": [await executor.tap(action) for action in actions]},
            )
        except Exception as exc:
            logger.exception("Mobile guided navigator failed")
            return ToolResult("mobile-guided-navigator", ToolStatus.FAILURE, {}, error=str(exc))


def _parse_actions(instructions: str) -> list[MobileTapAction]:
    hint = _position_hint(instructions)
    actions = []
    for match in TAP_RE.finditer(instructions):
        target = _clean_target(match.group(1))
        if target.casefold() not in IGNORED_TARGETS:
            actions.append(MobileTapAction(target, hint))
    return actions


def _position_hint(instructions: str) -> PositionHint | None:
    normalized = " ".join(instructions.casefold().split())
    for label, hint in HINTS.items():
        if label in normalized:  # FIXME: upgrade: use regex or something more robust + expand to other languages
            return hint
    return None


def _clean_target(target: str) -> str:
    normalized = " ".join(target.strip().split())
    for label in HINTS:
        normalized = re.sub(rf"\s+{re.escape(label)}$", "", normalized, flags=re.I)
    return normalized.strip()
