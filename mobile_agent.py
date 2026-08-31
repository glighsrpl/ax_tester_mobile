"""ADK entrypoint for the mobile ax-tester agent."""

import asyncio
import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Protocol

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from mobile_tools.guided_navigator import MobileGuidedNavigatorTool
from mobile_tools.screen_scanner import MobileScanSnapshot, MobileScreenScannerTool
from mobile_tools.utils.queue_utils import StaticAnalyzer, consume_static_snapshots
from mobile_tools.utils.report_utils import (
    deterministic_report,
    flatten_issues_by_activity,
    issues_by_activity,
    merge_static_reports,
    save_source_reports,
)
from mobile_tools.utils.session import MOBILE_SESSION
from mobile_tools.utils.snapshot_utils import build_static_debug_payload, build_static_snapshot_payload
from mobile_tools.utils.static_analysis_utils import StaticSnapshotReports, run_mobile_merge, run_static_snapshot
from schemas import Issue, Report
from tools.saver_tool import generate_run_timestamp
from utils.report_store import REPORTS_ROOT

logger = logging.getLogger(__name__)

MAX_CONCURRENT_STATIC_ANALYSES = 4

__all__ = ["flatten_issues_by_activity", "mobile_root_agent", "run_mobile_test"]


@dataclass(frozen=True)
class _StaticAnalysisResult:
    report: Report
    deterministic_report: Report
    contrast_report: Report
    llm_report: Report
    issues_by_activity: dict[str, list[Issue]]
    debug_data: list[dict[str, object]]


class _SnapshotNavigator(Protocol):
    def navigate(self) -> AsyncGenerator[MobileScanSnapshot, None]: ...

    def result(self) -> dict[str, object]: ...


class _MobileStaticAnalyzer:
    async def analyze(self, snapshot: MobileScanSnapshot, snapshot_index: int) -> dict[str, object]:
        snapshot_payload = build_static_snapshot_payload(snapshot, snapshot_index)
        debug_data = build_static_debug_payload(snapshot_payload)
        try:
            llm_reports = await run_static_snapshot(snapshot_payload)
        except Exception:
            logger.exception("LLM static analysis failed for snapshot %s", snapshot.snapshot_id)
            llm_reports = _empty_llm_reports(snapshot)
        return {
            "deterministic_report": deterministic_report(snapshot),
            "contrast_report": llm_reports.contrast_report,
            "llm_report": llm_reports.llm_report,
            "debug_data": debug_data,
        }


def _empty_llm_reports(snapshot: MobileScanSnapshot) -> StaticSnapshotReports:
    page = f"mobile://{snapshot.activity}"
    metadata = [{"key": "snapshot_id", "value": snapshot.snapshot_id}]
    return StaticSnapshotReports(
        contrast_report=Report(
            tool_name="contrast_agent",
            total_issues=0,
            page=page,
            issue_list=[],
            metadata=metadata,
        ),
        llm_report=Report(
            tool_name="llm",
            total_issues=0,
            page=page,
            issue_list=[],
            metadata=metadata,
        ),
    )


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

    await MOBILE_SESSION.connect(capability_id, app_package=app_package, app_activity=app_activity)
    page_source = await MOBILE_SESSION.get_accessibility_tree()
    serial = capability_id.removeprefix("local-android:")
    if not page_source or len(page_source) < 100:
        raise RuntimeError(f"Empty UI tree from device {serial}, session may not be ready")

    try:
        guided_path = await _run_guided_navigation(resolved_instructions, resolved_max_steps)
        report_id = f"{generate_run_timestamp()}_{_report_label(app_package)}"
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
        save_source_reports(
            REPORTS_ROOT / report_id / "static_reports",
            static_analysis.deterministic_report,
            static_analysis.contrast_report,
            static_analysis.llm_report,
        )
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
        "activities": _activity_count(navigator_data),
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
    static_agent: StaticAnalyzer,
) -> tuple[dict[str, object], _StaticAnalysisResult]:
    queue: asyncio.Queue[tuple[int, MobileScanSnapshot] | None] = asyncio.Queue()
    async with asyncio.TaskGroup() as task_group:
        workers = [
            task_group.create_task(consume_static_snapshots(queue, static_agent))
            for _ in range(MAX_CONCURRENT_STATIC_ANALYSES)
        ]
        try:
            async for snapshot_index, snapshot in _indexed_snapshots(navigator):
                await queue.put((snapshot_index, snapshot))
        finally:
            for _ in workers:
                await queue.put(None)

    analyses = sorted(
        (analysis for worker in workers for analysis in worker.result()),
        key=lambda analysis: analysis.snapshot_index,
    )
    navigator_data = navigator.result()
    deterministic = merge_static_reports(
        [analysis.deterministic_report for analysis in analyses], len(analyses), tool_name="deterministic"
    )
    contrast = merge_static_reports(
        [analysis.contrast_report for analysis in analyses], len(analyses), tool_name="contrast_agent"
    )
    llm = merge_static_reports([analysis.llm_report for analysis in analyses], len(analyses), tool_name="llm")
    activity_issues = issues_by_activity(analyses, navigator_data)
    return navigator_data, _StaticAnalysisResult(
        report=await _merge_reports(deterministic, contrast, llm, activity_issues),
        deterministic_report=deterministic,
        contrast_report=contrast,
        llm_report=llm,
        issues_by_activity=activity_issues,
        debug_data=[analysis.debug_data for analysis in analyses],
    )


async def _indexed_snapshots(
    navigator: _SnapshotNavigator,
) -> AsyncGenerator[tuple[int, MobileScanSnapshot], None]:
    snapshot_index = 0
    async for snapshot in navigator.navigate():
        yield snapshot_index, snapshot
        snapshot_index += 1


async def _merge_reports(
    deterministic: Report,
    contrast: Report,
    llm: Report,
    activity_issues: dict[str, list[Issue]],
) -> Report:
    if not deterministic.issue_list and not contrast.issue_list and not llm.issue_list:
        return merge_static_reports([], 0, activity_issues, tool_name="mobile")
    return await run_mobile_merge(deterministic, contrast, llm)
