import json
import logging
import re
from typing import Any

from common import MODEL_NAME, ContextKey
from schemas import Issue, ScoreInfo
from tools.base import ActiveElementInfo, NavigatorState
from tools.consumers.base import BaseConsumer
from utils.browser_session import NavigationCommand
from utils.llm_helper import call_llm
from utils.wcag_helper import get_rule_name_from_axe_tags

logger = logging.getLogger(__name__)

WCAG_RULE = get_rule_name_from_axe_tags(["wcag212"])

ESCAPE_MODAL_PROMPT = """
You are validating WCAG 2.1.2 (No Keyboard Trap) behavior after pressing Escape.
You receive six screenshots:
- ROOT page screenshot: page state before modal expansion (before Space press).
- ROOT element screenshot: focused area before modal expansion.
- BEFORE_ESCAPE page screenshot: full page state before Escape.
- BEFORE_ESCAPE element screenshot: focused area before Escape.
- AFTER_ESCAPE page screenshot: full page state after Escape.
- AFTER_ESCAPE element screenshot: focused area after Escape.

Determine:
1) Was a modal/dialog/overlay/popup visibly open before Escape?
2) If yes, did Escape close it after Escape?

Decision policy:
- Use page screenshots as the primary source for modal presence/absence.
- Use element screenshots as supporting evidence near focused controls.
- ROOT screenshots represent the expected baseline after a successful close.
- Consider modal_closed_after_escape=true when AFTER_ESCAPE is substantially similar to ROOT:
  no visible dialog container, no backdrop/overlay, and page structure looks like the baseline.
- Small differences are acceptable (animations, dynamic counters, time, ads, async content).
- If AFTER_ESCAPE still looks like BEFORE_ESCAPE with modal/backdrop visible, set modal_closed_after_escape=false.
- If no modal is visible before Escape, set:
  modal_was_present_before_escape=false
  modal_closed_after_escape=true

Return JSON ONLY with this schema:
{
  "modal_was_present_before_escape": boolean,
  "modal_closed_after_escape": boolean,
  "reason": "short explanation"
}

Rules:
- Keep reason concise and visual (for example: backdrop still visible, dialog container still present, etc.).
- Do not add extra keys or extra text.
"""


class NoKeyboardTrapConsumer(BaseConsumer):
    """Detect WCAG 2.1.2 violations when Escape fails to close an open modal."""

    name = "no-keyboard-trap-consumer"
    report_key = ContextKey.NO_KEYBOARD_TRAP_REPORT

    def __init__(self):
        self._issues: list[dict[str, Any]] = []
        self._steps = 0
        self._checked = 0

    def consume(self, state: NavigatorState, **kwargs) -> None:
        self._steps += 1

        previous = state.prv_active_element
        current = state.cur_active_element
        root_element = state.root_element
        if not root_element or not previous or not current or not state.path:
            return

        transition_key = state.path[-1]
        if transition_key != NavigationCommand.ESCAPE.value or NavigationCommand.SPACE.value not in state.path:
            return

        self._checked += 1

        issue = self._build_issue(root_element=root_element, previous=previous, current=current)
        if issue is not None:
            self._issues.append(issue)

    def finalize(self) -> dict[str, Any]:
        """Run LLM analysis and build issues."""
        logger.info(f"Start finalization of {self.__class__.__name__} consumer")

        return {
            "name": self.name,
            "issue_list": self._issues,
            "checked": self._checked,
            "score_passed": ScoreInfo(level_A=self._checked - len(self._issues)),
            "score_total": ScoreInfo(level_A=self._checked),
        }

    def _build_issue(
        self, root_element: ActiveElementInfo, previous: ActiveElementInfo, current: ActiveElementInfo
    ) -> dict[str, Any] | None:

        response_text = call_llm(MODEL_NAME, 0.0, self._build_llm_messages(root_element, previous, current))
        decision = self._parse_llm_response(response_text)
        if decision is None:
            return None

        modal_before = bool(decision.get("modal_was_present_before_escape"))
        modal_closed_after = bool(decision.get("modal_closed_after_escape"))
        if not modal_before or modal_closed_after:
            return None

        reason = str(decision.get("reason") or "").strip()
        description = "Pressing Escape did not close the open modal/dialog, creating a potential keyboard trap."
        if reason:
            description = f"{description} Evidence: {reason}"

        return Issue(
            id=f"no-keyboard-trap-{current.backend_dom_node_id or 'unknown'}-{self._steps}",
            wcag_rule=WCAG_RULE,
            description=description,
            severity="serious",
            source="llm/no_keyboard_trap",
            confidence="medium",
            html_snippet=current.element_out_html or previous.element_out_html or "",
            fix="Ensure Escape closes the active modal/dialog and returns keyboard users to the underlying page context.",
            image_url_or_path=None,
            why_this_matters="Keyboard users may be stuck inside a modal and unable to continue or leave the flow.",
            potential_exposures=[
                {
                    "category": "User blocked",
                    "description": "People using only the keyboard may be unable to close the dialog or continue.",
                },
            ],
        ).model_dump()

    def _build_llm_messages(
        self, root_element: ActiveElementInfo, previous: ActiveElementInfo, current: ActiveElementInfo
    ) -> list[dict[str, Any]]:

        data_str: str = "data:image/png;base64"
        return [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": ESCAPE_MODAL_PROMPT.strip()},
                    {"type": "text", "text": "ROOT page screenshot"},
                    {"type": "image_url", "image_url": {"url": f"{data_str},{root_element.page_screenshot}"}},
                    {"type": "text", "text": "ROOT element screenshot"},
                    {"type": "image_url", "image_url": {"url": f"{data_str},{root_element.element_screenshot}"}},
                    {"type": "text", "text": "BEFORE_ESCAPE page screenshot"},
                    {"type": "image_url", "image_url": {"url": f"{data_str},{previous.page_screenshot}"}},
                    {"type": "text", "text": "BEFORE_ESCAPE element screenshot"},
                    {"type": "image_url", "image_url": {"url": f"{data_str},{previous.element_screenshot}"}},
                    {"type": "text", "text": "AFTER_ESCAPE page screenshot"},
                    {"type": "image_url", "image_url": {"url": f"{data_str},{current.page_screenshot}"}},
                    {"type": "text", "text": "AFTER_ESCAPE element screenshot"},
                    {"type": "image_url", "image_url": {"url": f"{data_str},{current.element_screenshot}"}},
                ],
            }
        ]

    def _parse_llm_response(self, text: str) -> dict[str, Any] | None:
        try:
            parsed = json.loads(text)
        except Exception:
            match = re.search(r"(\{.*\})", text, re.DOTALL)
            if not match:
                return None
            try:
                parsed = json.loads(match.group(1))
            except Exception:
                return None

        if not isinstance(parsed, dict):
            return None
        return parsed


if __name__ == "__main__":
    import asyncio
    import json
    import sys

    from tools import RuntimeNavigatorTool
    from utils.browser_session import BROWSER_SESSION

    default_url = "https://shop.reply.com"
    # default_url = "https://apple.com"
    test_url = default_url if len(sys.argv) < 2 else sys.argv[1]

    async def _run() -> None:
        url = test_url if test_url.startswith(("http://", "https://")) else f"https://{test_url}"
        await BROWSER_SESSION.create_session()
        await BROWSER_SESSION.goto(url)
        try:
            result = (await RuntimeNavigatorTool({"consumers": [NoKeyboardTrapConsumer()]}).execute()).to_dict()
            print(json.dumps(result, indent=2, ensure_ascii=False))
        finally:
            await BROWSER_SESSION.close_session()

    asyncio.run(_run())
