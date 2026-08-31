"""ADK entrypoint for the mobile ax-tester agent."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from uuid import uuid4

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.runners import InMemoryRunner, Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.adk.utils.context_utils import Aclosing
from google.genai import types

from common import MODEL, MobileContextKey
from mobile_agents.navigation_agent import mobile_navigator_agent
from mobile_agents.static_agent import mobile_static_analysis_agent
from mobile_tools.base import MobileElementInfo
from mobile_tools.utils.session import MOBILE_SESSION
from schemas import Issue, Report, ScoreInfo

logger = logging.getLogger(__name__)

MAX_STATIC_ELEMENTS = 120
MAX_STATIC_TREE_LINES = 120
MAX_TEXT_CHARS = 160
MAX_KEYBOARD_TRAPS = 10


@dataclass(frozen=True)
class _StaticSnapshotScope:
    index: int
    total: int
    keyboard_results: object


@dataclass(frozen=True)
class _StaticAnalysisResult:
    report: Report
    debug_data: list[dict[str, object]]


MOBILE_ROOT_AGENT_INSTRUCTION = """
You are the root orchestrator for Android mobile accessibility testing.

Use only this tool:
- `run_mobile_test(max_steps, instructions, max_activities, max_depth)`

Rules:
1. The Android app target is provided by the caller.
2. Call `run_mobile_test` exactly once.
3. Pass explicit tap/click/open/navigation requests through `instructions`.
4. Pass empty `instructions` for a plain current-screen accessibility scan.
5. Do not ask for confirmations.
6. Return a short summary with tested activities.
"""


async def run_mobile_test(
    tool_context: ToolContext,
    max_steps: int = 500,
    instructions: str = "",
    max_activities: int = 3,
    max_depth: int = 5,
) -> dict[str, object]:
    app_package = _state_str(tool_context, MobileContextKey.APP_PACKAGE)
    app_activity = _state_str(tool_context, MobileContextKey.APP_ACTIVITY)
    capability_id = _state_str(tool_context, MobileContextKey.CAPABILITY_ID)
    if not app_package or not app_activity or not capability_id:
        raise ValueError("Missing mobile app package, activity, or capability id.")

    resolved_max_steps = max(int(max_steps), 1)
    resolved_max_activities = max(int(max_activities), 1)
    resolved_max_depth = max(int(max_depth), 0)
    resolved_instructions = instructions.strip() or _state_str(tool_context, MobileContextKey.INSTRUCTIONS)
    tool_context.state[MobileContextKey.MAX_STEPS] = resolved_max_steps
    tool_context.state[MobileContextKey.MAX_ACTIVITIES] = resolved_max_activities
    tool_context.state[MobileContextKey.MAX_DEPTH] = resolved_max_depth
    tool_context.state[MobileContextKey.INSTRUCTIONS] = resolved_instructions

    # Connect to the mobile device and retrieve the current accessibility tree
    await MOBILE_SESSION.connect(
        capability_id,
        app_package=app_package,
        app_activity=app_activity,
    )
    page_source = await MOBILE_SESSION.get_accessibility_tree()
    serial = (
        capability_id.removeprefix("local-android:")
        if capability_id.startswith("local-android:")
        else capability_id
    )
    if not page_source or len(page_source) < 100:
        raise RuntimeError(f"Empty UI tree from device {serial}, session may not be ready")

    session_service = InMemorySessionService()
    runner = Runner(
        app_name="mobile_ax_tester_internal",
        agent=mobile_tester_agent,
        session_service=session_service,
    )
    session_id = str(uuid4())
    state_copy = {
        str(MobileContextKey.APP_PACKAGE): app_package,
        str(MobileContextKey.APP_ACTIVITY): app_activity,
        str(MobileContextKey.CAPABILITY_ID): capability_id,
        str(MobileContextKey.MAX_STEPS): resolved_max_steps,
        str(MobileContextKey.MAX_ACTIVITIES): resolved_max_activities,
        str(MobileContextKey.MAX_DEPTH): resolved_max_depth,
        str(MobileContextKey.INSTRUCTIONS): resolved_instructions,
    }
    logger.info(
        "Running mobile sub-runner with state keys=%s and page_source length=%s",
        list(state_copy.keys()),
        len(page_source),
    )
    await session_service.create_session(
        app_name="mobile_ax_tester_internal",
        user_id="mobile_user",
        session_id=session_id,
        state=state_copy,
    )

    prefix = (
        f"Follow these mobile navigation instructions: {resolved_instructions}\n\n"
        if resolved_instructions
        else ""
    )
    content = types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    prefix
                    + "Run the Android mobile accessibility navigator now.\n\n"
                    + f"Current screen UI tree:\n{page_source[:50000]}"
                )
            )
        ],
    )
    final_response = ""
    try:
        async with Aclosing(
            runner.run_async(
                user_id="mobile_user",
                session_id=session_id,
                new_message=content,
            )
        ) as event_stream:
            async for event in event_stream:
                if event.content and event.content.parts and (event.author or "").lower() != "user":
                    final_response = "".join(part.text or "" for part in event.content.parts).strip()
    except Exception as exc:
        logger.exception("Mobile sub-runner failed")
        raise RuntimeError(f"Mobile sub-runner failed: {exc}") from exc

    session = await session_service.get_session(
        app_name="mobile_ax_tester_internal",
        user_id="mobile_user",
        session_id=session_id,
    )
    state = dict(session.state) if session else {}
    navigator_data = state.get(MobileContextKey.NAVIGATOR_DATA) or state.get(
        str(MobileContextKey.NAVIGATOR_DATA)
    )
    if isinstance(navigator_data, dict):
        tool_context.state[MobileContextKey.NAVIGATOR_DATA] = navigator_data

    # Run static accessibility analysis on the collected snapshots and store results
    static_analysis = await _run_static_analysis(navigator_data)
    static_results = static_analysis.report.model_dump(mode="json")
    tool_context.state[MobileContextKey.STATIC_RESULTS] = static_results
    tool_context.state[MobileContextKey.STATIC_DEBUG_DATA] = static_analysis.debug_data

    return {
        "status": "success",
        "activities": _activity_count(navigator_data) if isinstance(navigator_data, dict) else 1,
        "final_response": final_response,
        "static_results": static_results,
    }


mobile_tester_agent = SequentialAgent(
    name="MobileAccessibilityTesterAgent",
    description="Runs Android mobile accessibility navigation.",
    sub_agents=[mobile_navigator_agent],
)

mobile_root_agent = LlmAgent(
    name="MobileRootAgent",
    model=MODEL,
    description="Orchestrates Android mobile accessibility testing.",
    instruction=MOBILE_ROOT_AGENT_INSTRUCTION,
    tools=[run_mobile_test],
)


def _state_str(tool_context: ToolContext, key: MobileContextKey) -> str:
    return str(tool_context.state.get(key) or tool_context.state.get(str(key)) or "").strip()


def _activity_count(data: dict[str, object]) -> int:
    activities = data.get("visited_activities") or []
    return len(activities) if isinstance(activities, list) else 0


async def _run_static_analysis(navigator_data: object) -> _StaticAnalysisResult:
    raw_snapshots = navigator_data.get("snapshots") if isinstance(navigator_data, dict) else None
    if not isinstance(raw_snapshots, list) or not raw_snapshots:
        logger.warning("Mobile navigator returned no snapshots; skipping static analysis")
        return _StaticAnalysisResult(report=_empty_static_report(), debug_data=[])

    reports: list[Report] = []
    debug_data: list[dict[str, object]] = []
    total_snapshots = len(raw_snapshots)
    keyboard_results = navigator_data.get("keyboard_results") if isinstance(navigator_data, dict) else None
    for index, raw_snapshot in enumerate(raw_snapshots):
        snapshot_payload = _static_snapshot_payload(
            raw_snapshot,
            _StaticSnapshotScope(index=index, total=total_snapshots, keyboard_results=keyboard_results),
        )
        debug_data.append(_static_debug_payload(snapshot_payload))
        reports.append(await _run_static_snapshot(snapshot_payload))

    return _StaticAnalysisResult(report=_merge_static_reports(reports, total_snapshots), debug_data=debug_data)


async def _run_static_snapshot(snapshot_payload: dict[str, object]) -> Report:
    runner = InMemoryRunner(agent=mobile_static_analysis_agent, app_name="mobile_static_analysis")
    session_id = str(uuid4())
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="mobile_user",
        session_id=session_id,
        state={str(MobileContextKey.NAVIGATOR_DATA): snapshot_payload},
    )
    content = types.Content(role="user", parts=[types.Part(text="Run mobile static analysis now.")])
    async for _ in runner.run_async(
        user_id="mobile_user",
        session_id=session_id,
        new_message=content,
    ):
        pass
    session = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id="mobile_user",
        session_id=session_id,
    )
    result = (
        session.state.get(MobileContextKey.STATIC_RESULTS)
        or session.state.get(str(MobileContextKey.STATIC_RESULTS))
        if session
        else None
    )
    return Report.model_validate_json(result) if isinstance(result, str) else Report.model_validate(result)


def _static_snapshot_payload(
    raw_snapshot: object,
    scope: _StaticSnapshotScope,
) -> dict[str, object]:
    elements = _relevant_static_elements(_snapshot_elements(raw_snapshot))
    activity = _snapshot_value(raw_snapshot, "activity") or ""
    snapshot_id = str(uuid4())
    return {
        "snapshot_id": snapshot_id,
        "snapshot_index": scope.index,
        "total_snapshots": scope.total,
        "activity": activity,
        "tree_summary": _limited_tree_summary(elements),
        "elements": [_element_payload(element) for element in elements],
        "keyboard_result": _keyboard_result_for_activity(scope.keyboard_results, activity),
    }


def _static_debug_payload(snapshot_payload: dict[str, object]) -> dict[str, object]:
    return {
        **snapshot_payload,
        "debug": {
            "payload_chars": len(str(snapshot_payload)),
            "element_count": _list_count(snapshot_payload.get("elements")),
            "tree_summary_lines": len(str(snapshot_payload.get("tree_summary") or "").splitlines()),
            "has_screenshot": "screenshot" in str(snapshot_payload).lower(),
            "has_tree_xml": "tree_xml" in snapshot_payload,
        },
    }


def _snapshot_elements(raw_snapshot: object) -> list[MobileElementInfo]:
    elements = _snapshot_value(raw_snapshot, "elements")
    return elements if isinstance(elements, list) else []


def _snapshot_value(raw_snapshot: object, name: str) -> object:
    if isinstance(raw_snapshot, dict):
        return raw_snapshot.get(name)
    return getattr(raw_snapshot, name, None)


def _relevant_static_elements(elements: list[MobileElementInfo]) -> list[MobileElementInfo]:
    relevant_elements = [element for element in elements if _is_static_relevant(element)]
    return relevant_elements[:MAX_STATIC_ELEMENTS]


def _is_static_relevant(element: MobileElementInfo) -> bool:
    return bool(
        element.is_interactive()
        or _trim_text(element.text)
        or _trim_text(element.content_desc)
        or _trim_text(element.hint)
        or _trim_text(element.label_for)
        or _is_semantic_class(element)
    )


def _is_semantic_class(element: MobileElementInfo) -> bool:
    class_name = (element.class_name or "").casefold()
    return any(name in class_name for name in ("image", "text", "edit", "button", "checkbox", "switch"))


def _limited_tree_summary(elements: list[MobileElementInfo]) -> str:
    return "\n".join(_compact_element_line(element) for element in elements[:MAX_STATIC_TREE_LINES])


def _compact_element_line(element: MobileElementInfo) -> str:
    label = _trim_text(element.get_label()) or "-"
    return (
        f"{element.index}: {element.class_name or '-'}"
        f" id={_trim_text(element.resource_id) or '-'}"
        f" label={label}"
        f" bounds={element.bounds or '-'}"
        f" states={_element_states(element) or '-'}"
    )


def _element_states(element: MobileElementInfo) -> str:
    return ",".join(
        state
        for state, enabled in (
            ("clickable", element.clickable),
            ("focusable", element.focusable),
            ("disabled", not element.enabled),
            ("selected", element.selected),
            ("checked", bool(element.checked)),
            ("expanded", bool(element.expanded)),
            ("focused", element.focused),
        )
        if enabled
    )


def _element_payload(element: MobileElementInfo) -> dict[str, object]:
    return {
        "index": element.index,
        "text": _trim_text(element.text),
        "content_desc": _trim_text(element.content_desc),
        "resource_id": _trim_text(element.resource_id),
        "class_name": _trim_text(element.class_name),
        "bounds": _trim_text(element.bounds),
        "clickable": element.clickable,
        "focusable": element.focusable,
        "enabled": element.enabled,
        "selected": element.selected,
        "checked": element.checked,
        "expanded": element.expanded,
        "focused": element.focused,
        "hint": _trim_text(element.hint),
        "label_for": _trim_text(element.label_for),
        "input_type": _trim_text(element.input_type),
        "parent_index": element.parent_index,
    }


def _keyboard_result_for_activity(keyboard_results: object, activity: str) -> object:
    if not isinstance(keyboard_results, list):
        return None
    keyboard_result = next(
        (
            keyboard_result
            for keyboard_result in keyboard_results
            if isinstance(keyboard_result, dict) and keyboard_result.get("activity") == activity
        ),
        None,
    )
    return _compact_keyboard_result(keyboard_result)


def _trim_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:MAX_TEXT_CHARS] if text else None


def _compact_keyboard_result(keyboard_result: object) -> dict[str, object] | None:
    if not isinstance(keyboard_result, dict):
        return None
    return {
        "activity": _trim_text(keyboard_result.get("activity")),
        "reachable_count": _list_count(keyboard_result.get("reachable")),
        "unreachable_count": _list_count(keyboard_result.get("unreachable")),
        "focus_order_count": _list_count(keyboard_result.get("focus_order")),
        "trap_count": _list_count(keyboard_result.get("traps")),
        "traps": _compact_keyboard_traps(keyboard_result.get("traps")),
    }


def _list_count(value: object) -> int:
    return len(value) if isinstance(value, list) else 0


def _compact_keyboard_traps(traps: object) -> list[str]:
    if not isinstance(traps, list):
        return []
    return [_trim_text(trap) or "" for trap in traps[:MAX_KEYBOARD_TRAPS]]


def _merge_static_reports(reports: list[Report], total_snapshots: int) -> Report:
    issues = _dedupe_issues(issue for report in reports for issue in report.issue_list)
    return Report(
        tool_name="llm",
        total_issues=len(issues),
        page="mobile",
        issue_list=issues,
        score_passed=_sum_scores(report.score_passed for report in reports),
        score_total=_sum_scores(report.score_total for report in reports),
        metadata=[{"key": "snapshots", "value": total_snapshots}],
    )


def _dedupe_issues(issues: Iterable[Issue]) -> list[Issue]:
    deduped: dict[tuple[str, str, str], Issue] = {}
    for issue in issues:
        if isinstance(issue, Issue):
            deduped.setdefault((issue.wcag_rule, issue.html_snippet, issue.description), issue)
    return list(deduped.values())


def _sum_scores(scores: Iterable[ScoreInfo]) -> ScoreInfo:
    total = ScoreInfo()
    for score in scores:
        if isinstance(score, ScoreInfo):
            total.level_A += score.level_A
            total.level_AA += score.level_AA
            total.level_AAA += score.level_AAA
    return total


def _empty_static_report() -> Report:
    return Report(
        tool_name="llm",
        total_issues=0,
        page="mobile",
        issue_list=[],
        metadata=[{"key": "snapshots", "value": 0}],
    )
