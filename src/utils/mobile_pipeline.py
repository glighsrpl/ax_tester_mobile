"""Reusable orchestration helpers for mobile static analysis."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from typing import Protocol

from schemas import Issue, Report
from tools.mobile_screen_scanner import MobileScanSnapshot
from utils.mobile_queue import SnapshotAnalysis, StaticAnalyzer, consume_static_snapshots
from utils.mobile_report import deterministic_report, merge_static_reports
from utils.mobile_snapshot import (
    build_cross_screen_summary,
    build_static_debug_payload,
    build_static_snapshot_payload,
)
from utils.mobile_static_analysis import (
    aggregate_source_reports,
    append_cross_screen_issues,
    empty_llm_reports,
    mobile_page,
    run_cross_screen_analysis,
    run_mobile_merge,
    run_static_snapshot,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StaticAnalysisResult:
    """Aggregated reports and debug payloads for a mobile scan."""

    report: Report
    activity_reports: dict[str, "ActivityReports"]
    issues_by_activity: dict[str, list[Issue]]
    debug_data: list[dict[str, object]]


@dataclass(frozen=True)
class ActivityReports:
    """Reports produced for one activity actually visited by the navigator."""

    deterministic: Report
    contrast: Report
    llm: Report
    merge: Report
    cross_screen: Report


class SnapshotNavigator(Protocol):
    """Provide snapshots and final navigation data to the analysis pipeline."""

    def navigate(self) -> AsyncGenerator[MobileScanSnapshot, None]: ...

    def result(self) -> dict[str, object]: ...


class MobileStaticAnalyzer:
    """Build independent deterministic and LLM reports for one snapshot."""

    def __init__(self, platform: str) -> None:
        self._platform = platform

    async def analyze(self, snapshot: MobileScanSnapshot, snapshot_index: int) -> dict[str, object]:
        snapshot_payload = build_static_snapshot_payload(snapshot, snapshot_index)
        debug_data = build_static_debug_payload(snapshot_payload)
        llm_result, deterministic_result = await asyncio.gather(
            run_static_snapshot(snapshot_payload, self._platform),
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
            "cross_screen_summary": build_cross_screen_summary(snapshot),
        }


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
    navigator_data: Mapping[str, object],
) -> StaticAnalysisResult:
    """Create source, merged, and cross-screen reports independently per activity."""
    app_package = str(navigator_data.get("app_package") or "unknown")
    activity_reports = {
        activity: await _activity_reports(activity, activity_analyses, navigator_data, app_package)
        for activity, activity_analyses in _analyses_by_activity(analyses).items()
    }
    activity_issues = {
        activity: [*reports.merge.issue_list, *reports.cross_screen.issue_list]
        for activity, reports in activity_reports.items()
    }
    report = merge_static_reports(
        [
            append_cross_screen_issues(reports.merge, reports.cross_screen)
            for reports in activity_reports.values()
        ],
        len(analyses),
        activity_issues,
        "static",
    )
    return StaticAnalysisResult(
        report=report,
        activity_reports=activity_reports,
        issues_by_activity=activity_issues,
        debug_data=[analysis.debug_data for analysis in analyses],
    )


def _analyses_by_activity(analyses: list[SnapshotAnalysis]) -> dict[str, list[SnapshotAnalysis]]:
    grouped: dict[str, list[SnapshotAnalysis]] = {}
    for analysis in analyses:
        grouped.setdefault(analysis.activity.strip() or "unknown", []).append(analysis)
    return grouped


async def _activity_reports(
    activity: str,
    analyses: list[SnapshotAnalysis],
    navigator_data: Mapping[str, object],
    app_package: str,
) -> ActivityReports:
    page = mobile_page(app_package, activity)
    deterministic, contrast, llm = aggregate_source_reports(
        analyses,
        navigator_data.get("snapshot_screenshots"),
        page=page,
    )
    cross_screen = await run_cross_screen_analysis(
        [analysis.cross_screen_summary for analysis in analyses],
        app_package,
        activity,
    )
    merge = (await run_mobile_merge(deterministic, contrast, llm)).model_copy(update={"page": page})
    return ActivityReports(deterministic, contrast, llm, merge, cross_screen)


async def _deterministic_snapshot_report(snapshot: MobileScanSnapshot) -> Report:
    """Adapt deterministic report generation for concurrent awaiting."""
    return deterministic_report(snapshot)
