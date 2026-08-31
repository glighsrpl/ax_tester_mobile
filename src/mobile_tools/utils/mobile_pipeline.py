"""Reusable orchestration helpers for mobile static analysis."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from typing import Protocol

from common import MobileContextKey
from mobile_tools.guided_navigator import MobileGuidedNavigatorTool
from mobile_tools.screen_scanner import MobileScanSnapshot
from mobile_tools.utils.queue_utils import SnapshotAnalysis, StaticAnalyzer, consume_static_snapshots
from mobile_tools.utils.report_utils import (
    deterministic_report,
    issues_by_activity,
    merge_static_reports,
)
from mobile_tools.utils.snapshot_utils import build_static_debug_payload, build_static_snapshot_payload
from mobile_tools.utils.static_analysis_utils import StaticSnapshotReports, run_mobile_merge, run_static_snapshot
from schemas import Issue, Report

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaticAnalysisResult:
    """Aggregated reports and debug payloads for a mobile scan."""

    report: Report
    deterministic_report: Report
    contrast_report: Report
    llm_report: Report
    issues_by_activity: dict[str, list[Issue]]
    debug_data: list[dict[str, object]]


class SnapshotNavigator(Protocol):
    """Provide snapshots and final navigation data to the analysis pipeline."""

    def navigate(self) -> AsyncGenerator[MobileScanSnapshot, None]: ...

    def result(self) -> dict[str, object]: ...


class MobileStaticAnalyzer:
    """Build independent deterministic and LLM reports for one snapshot."""

    async def analyze(self, snapshot: MobileScanSnapshot, snapshot_index: int) -> dict[str, object]:
        snapshot_payload = build_static_snapshot_payload(snapshot, snapshot_index)
        debug_data = build_static_debug_payload(snapshot_payload)
        llm_result, deterministic_result = await asyncio.gather(
            run_static_snapshot(snapshot_payload),
            _deterministic_snapshot_report(snapshot),
            return_exceptions=True,
        )
        if isinstance(deterministic_result, Exception):
            raise deterministic_result
        if isinstance(llm_result, Exception):
            logger.error(
                "LLM static analysis failed for snapshot %s: %s",
                snapshot.snapshot_id,
                llm_result,
            )
            llm_result = empty_llm_reports(snapshot)
        return {
            "deterministic_report": deterministic_result,
            "contrast_report": llm_result.contrast_report,
            "llm_report": llm_result.llm_report,
            "debug_data": debug_data,
        }


async def run_guided_navigation(instructions: str, max_steps: int) -> list[str]:
    """Run optional guided navigation and return its recorded path."""
    if not instructions:
        return []
    result = await MobileGuidedNavigatorTool({"instructions": instructions, "max_steps": max_steps}).execute()
    if not result.is_success():
        raise RuntimeError(result.error or "Mobile guided navigation failed.")
    return result.data.get("path", []) if isinstance(result.data, dict) else []


async def run_mobile_pipeline(
    navigator: SnapshotNavigator,
    static_agent: StaticAnalyzer,
    max_concurrent_analyses: int,
) -> tuple[dict[str, object], StaticAnalysisResult]:
    """Analyze streamed snapshots concurrently and aggregate their reports."""
    queue: asyncio.Queue[tuple[int, MobileScanSnapshot] | None] = asyncio.Queue()
    async with asyncio.TaskGroup() as task_group:
        workers = [
            task_group.create_task(consume_static_snapshots(queue, static_agent))
            for _ in range(max_concurrent_analyses)
        ]
        try:
            async for snapshot_index, snapshot in indexed_snapshots(navigator):
                await queue.put((snapshot_index, snapshot))
        finally:
            for _ in workers:
                await queue.put(None)

    analyses = sorted(
        (analysis for worker in workers for analysis in worker.result()),
        key=lambda analysis: analysis.snapshot_index,
    )
    navigator_data = navigator.result()
    return navigator_data, await aggregate_static_analyses(analyses, navigator_data)


async def indexed_snapshots(
    navigator: SnapshotNavigator,
) -> AsyncGenerator[tuple[int, MobileScanSnapshot], None]:
    """Yield snapshots with stable zero-based indexes."""
    snapshot_index = 0
    async for snapshot in navigator.navigate():
        yield snapshot_index, snapshot
        snapshot_index += 1


async def aggregate_static_analyses(
    analyses: list[SnapshotAnalysis],
    navigator_data: dict[str, object],
) -> StaticAnalysisResult:
    """Merge source reports and preserve per-activity issues and debug payloads."""
    deterministic = merge_static_reports(
        [analysis.deterministic_report for analysis in analyses], len(analyses), tool_name="deterministic"
    )
    contrast = merge_static_reports(
        [analysis.contrast_report for analysis in analyses], len(analyses), tool_name="contrast_agent"
    )
    llm = merge_static_reports([analysis.llm_report for analysis in analyses], len(analyses), tool_name="llm")
    activity_issues = issues_by_activity(analyses, navigator_data)
    return StaticAnalysisResult(
        report=await merge_reports(deterministic, contrast, llm, activity_issues),
        deterministic_report=deterministic,
        contrast_report=contrast,
        llm_report=llm,
        issues_by_activity=activity_issues,
        debug_data=[analysis.debug_data for analysis in analyses],
    )


def state_string(state: Mapping[object, object], key: MobileContextKey) -> str:
    """Return a trimmed string value from enum or string context keys."""
    return str(state.get(key) or state.get(str(key)) or "").strip()


def activity_count(data: Mapping[str, object]) -> int:
    """Return the number of visited activities in navigator output."""
    activities = data.get("visited_activities") or []
    return len(activities) if isinstance(activities, list) else 0


def report_label(value: str) -> str:
    """Convert an app identifier into a safe report-directory label."""
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-") or "mobile"


def empty_llm_reports(snapshot: MobileScanSnapshot) -> StaticSnapshotReports:
    """Return valid empty reports when an LLM analysis cannot complete."""
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


async def _deterministic_snapshot_report(snapshot: MobileScanSnapshot) -> Report:
    """Adapt deterministic report generation for concurrent awaiting."""
    return deterministic_report(snapshot)


async def merge_reports(
    deterministic: Report,
    contrast: Report,
    llm: Report,
    activity_issues: dict[str, list[Issue]],
) -> Report:
    """Return an empty aggregate or ask the LLM to merge source reports."""
    if not deterministic.issue_list and not contrast.issue_list and not llm.issue_list:
        return merge_static_reports([], 0, activity_issues, tool_name="mobile")
    return await run_mobile_merge(deterministic, contrast, llm)
