"""ADK entrypoint for the mobile ax-tester agent."""

import asyncio
import json
import logging
from collections.abc import AsyncGenerator, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from google.adk.agents.llm_agent import LlmAgent
from google.adk.runners import InMemoryRunner
from google.adk.tools.tool_context import ToolContext
from google.genai import types

from common import MODEL, MobileContextKey
from mobile_agents.static_agent import mobile_merge_agent, mobile_static_analysis_agent
from mobile_agents.static_agent.deterministic_consumers import run_deterministic_analysis
from mobile_tools.base import MobileElementInfo
from mobile_tools.guided_navigator import MobileGuidedNavigatorTool
from mobile_tools.screen_scanner import MobileScanSnapshot, MobileScreenScannerTool
from mobile_tools.utils.session import MOBILE_SESSION
from schemas import Issue, Report, ScoreInfo
from tools.saver_tool import generate_run_timestamp
from utils.report_store import REPORTS_ROOT

logger = logging.getLogger(__name__)

MAX_STATIC_ELEMENTS = 120
MAX_STATIC_TREE_LINES = 120
MAX_TEXT_CHARS = 160
MAX_CONCURRENT_STATIC_ANALYSES = 4


@dataclass(frozen=True)
class _StaticAnalysisResult:
    report: Report
    deterministic_report: Report
    llm_report: Report
    issues_by_activity: dict[str, list[Issue]]
    debug_data: list[dict[str, object]]


@dataclass(frozen=True)
class _SnapshotAnalysis:
    snapshot_index: int
    activity: str
    snapshot_id: str
    deterministic_report: Report
    llm_report: Report
    debug_data: dict[str, object]


@dataclass(frozen=True)
class _PipelineQueues:
    static: asyncio.Queue[tuple[int, MobileScanSnapshot] | None]


class _SnapshotNavigator(Protocol):
    def navigate(self) -> AsyncGenerator[MobileScanSnapshot, None]: ...

    def result(self) -> dict[str, object]: ...


class _StaticAnalyzer(Protocol):
    async def analyze(self, snapshot: MobileScanSnapshot, snapshot_index: int) -> dict[str, object]: ...


class _MobileStaticAnalyzer:
    async def analyze(self, snapshot: MobileScanSnapshot, snapshot_index: int) -> dict[str, object]:
        snapshot_payload = _static_snapshot_payload(snapshot, snapshot_index)
        deterministic_report = _deterministic_report(snapshot)
        llm_report = await _run_static_snapshot(snapshot_payload)
        return {
            "deterministic_report": deterministic_report,
            "llm_report": llm_report,
            "debug_data": _static_debug_payload(snapshot_payload),
        }


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

    try:
        guided_path = await _run_guided_navigation(resolved_instructions, resolved_max_steps)
        report_id = _mobile_report_id(app_package)
        navigator = MobileScreenScannerTool(
            {
                "max_steps": resolved_max_steps,
                "max_activities": resolved_max_activities,
                "max_depth": resolved_max_depth,
                "target_app_package": app_package,
                "run_id": report_id,
                "screenshot_output_dir": str(REPORTS_ROOT / report_id / "screenshots"),
            }
        )
        navigator_data, static_analysis = await _run_mobile_pipeline(navigator, _MobileStaticAnalyzer())
        navigator_data["report_id"] = report_id
        navigator_data["path"] = [*guided_path, *navigator_data.get("path", [])]
        _save_source_reports(REPORTS_ROOT / report_id / "static_reports", static_analysis)
    finally:
        try:
            await MOBILE_SESSION.terminate_app(app_package)
        except Exception:
            logger.warning("Unable to terminate app %s", app_package, exc_info=True)
        await MOBILE_SESSION.disconnect()

    tool_context.state[MobileContextKey.NAVIGATOR_DATA] = navigator_data
    static_results = static_analysis.report.model_dump(mode="json")
    static_results["issues_by_activity"] = {
        activity: [issue.model_dump(mode="json") for issue in issues]
        for activity, issues in static_analysis.issues_by_activity.items()
    }
    tool_context.state[MobileContextKey.STATIC_RESULTS] = static_results
    tool_context.state[MobileContextKey.STATIC_DEBUG_DATA] = static_analysis.debug_data

    return {
        "status": "success",
        "activities": _activity_count(navigator_data) if isinstance(navigator_data, dict) else 1,
        "final_response": "Mobile navigation and static analysis completed.",
        "static_results": static_results,
    }


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


def _mobile_report_id(app_package: str) -> str:
    return f"{generate_run_timestamp()}_{_report_label(app_package)}"


def _report_label(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-") or "mobile"


async def _run_guided_navigation(instructions: str, max_steps: int) -> list[str]:
    if not instructions:
        return []
    result = await MobileGuidedNavigatorTool({"instructions": instructions, "max_steps": max_steps}).execute()
    if not result.is_success():
        raise RuntimeError(result.error or "Mobile guided navigation failed.")
    return result.data.get("path", []) if isinstance(result.data, dict) else []


async def _run_mobile_pipeline(
    navigator: _SnapshotNavigator,
    static_agent: _StaticAnalyzer,
) -> tuple[dict[str, object], _StaticAnalysisResult]:
    queues = _PipelineQueues(static=asyncio.Queue())
    static_task = asyncio.create_task(_consume_static_snapshots(queues.static, static_agent))
    analyses: list[_SnapshotAnalysis] = []
    try:
        snapshot_index = 0
        async for snapshot in navigator.navigate():
            await queues.static.put((snapshot_index, snapshot))
            snapshot_index += 1
    finally:
        for _ in range(MAX_CONCURRENT_STATIC_ANALYSES):
            await queues.static.put(None)
        analyses = await static_task

    navigator_data = navigator.result()
    deterministic_reports = [analysis.deterministic_report for analysis in analyses]
    llm_reports = [analysis.llm_report for analysis in analyses]
    deterministic_report = _merge_static_reports(deterministic_reports, len(analyses), tool_name="deterministic")
    llm_report = _merge_static_reports(llm_reports, len(analyses), tool_name="llm")
    issues_by_activity = _issues_by_activity(analyses, navigator_data)
    return navigator_data, _StaticAnalysisResult(
        report=await _merge_reports(deterministic_report, llm_report, issues_by_activity),
        deterministic_report=deterministic_report,
        llm_report=llm_report,
        issues_by_activity=issues_by_activity,
        debug_data=[analysis.debug_data for analysis in analyses],
    )


async def _consume_static_snapshots(
    queue: asyncio.Queue[tuple[int, MobileScanSnapshot] | None],
    static_agent: _StaticAnalyzer,
) -> list[_SnapshotAnalysis]:
    workers = [
        asyncio.create_task(_consume_static_snapshots_worker(queue, static_agent))
        for _ in range(MAX_CONCURRENT_STATIC_ANALYSES)
    ]
    worker_results = await asyncio.gather(*workers)
    analyses = [analysis for worker_result in worker_results for analysis in worker_result]
    return sorted(analyses, key=lambda analysis: analysis.snapshot_index)


async def _consume_static_snapshots_worker(
    queue: asyncio.Queue[tuple[int, MobileScanSnapshot] | None],
    static_agent: _StaticAnalyzer,
) -> list[_SnapshotAnalysis]:
    analyses: list[_SnapshotAnalysis] = []
    while (item := await queue.get()) is not None:
        snapshot_index, snapshot = item
        try:
            result = await static_agent.analyze(snapshot, snapshot_index)
            deterministic_report = result.get("deterministic_report")
            llm_report = result.get("llm_report")
            debug_data = result.get("debug_data")
            if not all(isinstance(value, Report) for value in (deterministic_report, llm_report)) or not isinstance(
                debug_data, dict
            ):
                raise TypeError("Static snapshot analysis returned an invalid result.")
            analyses.append(
                _SnapshotAnalysis(
                    snapshot_index=snapshot_index,
                    activity=snapshot.activity,
                    snapshot_id=snapshot.snapshot_id,
                    deterministic_report=deterministic_report,
                    llm_report=llm_report,
                    debug_data=debug_data,
                )
            )
        except Exception:
            logger.exception("Static analysis failed for mobile snapshot; continuing pipeline")
    return analyses


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


async def _run_mobile_merge(deterministic_report: Report, llm_report: Report) -> Report:
    runner = InMemoryRunner(agent=mobile_merge_agent, app_name="mobile_static_merge")
    session_id = str(uuid4())
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="mobile_user",
        session_id=session_id,
        state={
            str(MobileContextKey.DETERMINISTIC_REPORT): deterministic_report.model_dump(mode="json"),
            str(MobileContextKey.LLM_REPORT): llm_report.model_dump(mode="json"),
        },
    )
    content = types.Content(role="user", parts=[types.Part(text="Merge the mobile accessibility reports now.")])
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
    result = session.state.get(MobileContextKey.STATIC_RESULTS) if session else None
    return Report.model_validate_json(result) if isinstance(result, str) else Report.model_validate(result)


async def _merge_reports(
    deterministic_report: Report,
    llm_report: Report,
    issues_by_activity: dict[str, list[Issue]],
) -> Report:
    if not deterministic_report.issue_list and not llm_report.issue_list:
        return _merge_static_reports([], 0, issues_by_activity, tool_name="mobile")
    return await _run_mobile_merge(deterministic_report, llm_report)


def _deterministic_report(snapshot: MobileScanSnapshot) -> Report:
    issues = run_deterministic_analysis(snapshot)
    return Report(
        tool_name="deterministic",
        total_issues=len(issues),
        page=f"mobile://{snapshot.activity}",
        issue_list=issues,
        metadata=[{"key": "snapshot_id", "value": snapshot.snapshot_id}],
    )


def _save_source_reports(report_dir: Path, static_analysis: _StaticAnalysisResult) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_report(report_dir / "deterministic.json", static_analysis.deterministic_report)
    _write_report(report_dir / "llm.json", static_analysis.llm_report)


def _write_report(path: Path, report: Report) -> None:
    path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")


def _static_snapshot_payload(
    snapshot: MobileScanSnapshot,
    snapshot_index: int,
) -> dict[str, object]:
    elements = _relevant_static_elements(snapshot.elements)
    return {
        "snapshot_id": snapshot.snapshot_id,
        "snapshot_index": snapshot_index,
        "activity": snapshot.activity,
        "tree_summary": _limited_tree_summary(elements),
        "elements": [_element_payload(element) for element in elements],
    }


def _static_debug_payload(snapshot_payload: dict[str, object]) -> dict[str, object]:
    elements = snapshot_payload.get("elements")
    return {
        **snapshot_payload,
        "debug": {
            "payload_chars": len(str(snapshot_payload)),
            "element_count": len(elements) if isinstance(elements, list) else 0,
            "tree_summary_lines": len(str(snapshot_payload.get("tree_summary") or "").splitlines()),
            "has_screenshot": "screenshot" in str(snapshot_payload).lower(),
            "has_tree_xml": "tree_xml" in snapshot_payload,
        },
    }


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


def _trim_text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:MAX_TEXT_CHARS] if text else None


def _issues_by_activity(
    analyses: list[_SnapshotAnalysis],
    navigator_data: dict[str, object],
) -> dict[str, list[Issue]]:
    activities = navigator_data.get("visited_activities")
    issues_by_activity: dict[str, list[Issue]] = (
        {str(activity).strip(): [] for activity in activities if str(activity).strip()}
        if isinstance(activities, list)
        else {}
    )
    for analysis in analyses:
        activity = analysis.activity.strip() or "unknown"
        activity_issues = issues_by_activity.setdefault(activity, [])
        screenshot_path = _snapshot_screenshot_path(navigator_data, analysis.snapshot_id)
        activity_issues.extend(
            issue.model_copy(update={"image_url_or_path": screenshot_path})
            for report in (analysis.deterministic_report, analysis.llm_report)
            for issue in report.issue_list
        )
    return {activity: _dedupe_issues(issues) for activity, issues in issues_by_activity.items()}


def _snapshot_screenshot_path(navigator_data: dict[str, object], snapshot_id: str) -> str | None:
    screenshots = navigator_data.get("snapshot_screenshots")
    if not isinstance(screenshots, dict):
        return None
    screenshot_path = screenshots.get(snapshot_id)
    return screenshot_path if isinstance(screenshot_path, str) and screenshot_path else None


def flatten_issues_by_activity(
    issues_by_activity: dict[str, list[Issue]],
) -> list[Issue]:
    """Return the legacy flat issue list without changing activity buckets."""
    return [issue for activity_issues in issues_by_activity.values() for issue in activity_issues]


def _merge_static_reports(
    reports: list[Report],
    total_snapshots: int,
    issues_by_activity: dict[str, list[Issue]] | None = None,
    tool_name: str = "llm",
) -> Report:
    activity_issues = issues_by_activity or {
        "unknown": _dedupe_issues(issue for report in reports for issue in report.issue_list)
    }
    issues = flatten_issues_by_activity(activity_issues)
    return Report(
        tool_name=tool_name,
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
