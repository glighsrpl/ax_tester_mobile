"""Reusable orchestration helpers for mobile static analysis."""

import asyncio
import logging
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from typing import Protocol

from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types

from common import MobileContextKey
from mobile_agents.semantic_agent.image_analyzer_agent import image_analyzer_agent
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
class AnalysisResult[ActivityReport]:
    """Aggregated report data for a mobile scan."""

    report: Report
    activity_reports: dict[str, ActivityReport]
    issues_by_activity: dict[str, list[Issue]]
    debug_data: list[dict[str, object]] | None


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
) -> tuple[dict[str, object], AnalysisResult[ActivityReports], AnalysisResult[Report]]:
    """Analyze streamed snapshots and aggregate static and semantic reports."""
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
    static_analysis, semantic_analysis = await asyncio.gather(
        aggregate_static_analyses(analyses, navigator_data),
        run_semantic_analysis(navigator_data),
    )
    return navigator_data, static_analysis, semantic_analysis


async def run_semantic_analysis(navigator_data: Mapping[str, object]) -> AnalysisResult[Report]:
    """Analyze every snapshot's images and aggregate reports by activity."""
    snapshots = navigator_data.get("snapshots")
    snapshot_items = snapshots if isinstance(snapshots, list) else []
    reports_by_activity: dict[str, list[Report]] = {}
    activity_snapshot_counts: dict[str, int] = {}
    failed_activities: set[str] = set()
    for snapshot_index, snapshot in enumerate(snapshot_items):
        if not isinstance(snapshot, Mapping):
            continue
        activity = str(snapshot.get("activity") or "unknown").strip() or "unknown"
        activity_snapshot_counts[activity] = activity_snapshot_counts.get(activity, 0) + 1
        if activity in failed_activities:
            continue
        try:
            report = await _analyze_semantic_snapshot(
                snapshot.get("screenshot"),
                snapshot.get("tree_xml"),
                snapshot_index,
            )
        except Exception:
            logger.exception("Semantic analysis failed for activity %s", activity)
            failed_activities.add(activity)
            reports_by_activity.pop(activity, None)
        else:
            reports_by_activity.setdefault(activity, []).append(report)
    activity_reports = {
        activity: (
            _empty_semantic_report(snapshot_count)
            if activity in failed_activities
            else _merge_semantic_reports(reports_by_activity.get(activity, []), snapshot_count)
        )
        for activity, snapshot_count in activity_snapshot_counts.items()
    }
    issues_by_activity = {activity: report.issue_list for activity, report in activity_reports.items()}
    return AnalysisResult(
        report=_merge_semantic_reports(
            list(activity_reports.values()),
            sum(activity_snapshot_counts.values()),
        ),
        activity_reports=activity_reports,
        issues_by_activity=issues_by_activity,
        debug_data=None,
    )


async def _analyze_semantic_snapshot(
    screenshot: object,
    tree_xml: object,
    snapshot_index: int,
) -> Report:
    session_service = InMemorySessionService()
    runner = Runner(
        agent=image_analyzer_agent,
        app_name="semantic_image_analyzer",
        session_service=session_service,
    )
    session = await session_service.create_session(
        app_name=runner.app_name,
        user_id="mobile_pipeline",
        session_id=f"semantic-snapshot-{snapshot_index}",
        state={"screenshot": screenshot, "tree_xml": tree_xml, "page": "mobile"},
    )
    message = types.Content(
        role="user",
        parts=[types.Part(text="Analyze the screenshot and XML tree in the session context.")],
    )
    async for event in runner.run_async(
        user_id=session.user_id,
        session_id=session.id,
        new_message=message,
    ):
        if event.actions is None:
            continue
        result = event.actions.state_delta.get(MobileContextKey.SEMANTIC_RESULTS)
        if result is not None:
            return Report.model_validate(result)
    raise RuntimeError("Semantic image analyzer did not return a report")


def _merge_semantic_reports(reports: list[Report], snapshot_count: int) -> Report:
    issues = [issue for report in reports for issue in report.issue_list]
    return _empty_semantic_report(snapshot_count).model_copy(
        update={"total_issues": len(issues), "issue_list": issues}
    )


def _empty_semantic_report(snapshot_count: int) -> Report:
    issues: list[Issue] = []
    return Report(
        tool_name="semantic_image_analyzer",
        total_issues=len(issues),
        page="mobile",
        issue_list=issues,
        metadata=[{"key": "snapshots", "value": snapshot_count}],
    )


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
) -> AnalysisResult[ActivityReports]:
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
    return AnalysisResult(
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
