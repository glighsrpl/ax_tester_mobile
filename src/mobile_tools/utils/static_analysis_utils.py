import asyncio
import base64
import mimetypes
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from google.adk.runners import InMemoryRunner
from google.genai import types

from common import MobileContextKey
from mobile_agents.static_agent import mobile_merge_agent, mobile_static_analysis_agent
from mobile_tools.screen_scanner import MobileScanSnapshot
from mobile_tools.utils.contrast_calculator import calculate_contrast_measurements
from mobile_tools.utils.queue_utils import SnapshotAnalysis
from mobile_tools.utils.report_utils import merge_static_reports
from schemas import Report

_SNAPSHOT_ID_PATTERN = re.compile(r"(?:^|;\s*)snapshot_id=([^;\s]+)")


@dataclass(frozen=True)
class StaticSnapshotReports:
    """Reports emitted by the visual and static sub-agents for one snapshot."""

    contrast_report: Report
    llm_report: Report


def empty_llm_reports(snapshot: MobileScanSnapshot) -> StaticSnapshotReports:
    """Return empty reports when a snapshot's LLM analysis cannot complete."""
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


def aggregate_source_reports(
    analyses: list[SnapshotAnalysis],
    screenshot_paths: object,
) -> tuple[Report, Report, Report]:
    """Aggregate source reports and retain the screenshot for every issue."""
    total_snapshots = len(analyses)
    deterministic = merge_static_reports(
        [
            _report_with_screenshot(analysis.deterministic_report, screenshot_paths, analysis.snapshot_id)
            for analysis in analyses
        ],
        total_snapshots,
        tool_name="deterministic",
    )
    contrast = merge_static_reports(
        [
            _report_with_screenshot(analysis.contrast_report, screenshot_paths, analysis.snapshot_id)
            for analysis in analyses
        ],
        total_snapshots,
        tool_name="contrast_agent",
    )
    llm = merge_static_reports(
        [
            _report_with_screenshot(analysis.llm_report, screenshot_paths, analysis.snapshot_id)
            for analysis in analyses
        ],
        total_snapshots,
        tool_name="llm",
    )
    return deterministic, contrast, llm


async def merge_reports_by_activity(
    analyses: list[SnapshotAnalysis],
    screenshot_paths: object,
) -> dict[str, Report]:
    """Return the merge-agent report for each scanned activity."""
    analyses_by_activity: dict[str, list[SnapshotAnalysis]] = {}
    for analysis in analyses:
        activity = analysis.activity.strip() or "unknown"
        analyses_by_activity.setdefault(activity, []).append(analysis)
    activities = list(analyses_by_activity)
    reports = await asyncio.gather(
        *(_merge_activity_reports(analyses_by_activity[activity], screenshot_paths) for activity in activities)
    )
    return dict(zip(activities, reports, strict=True))


async def run_static_snapshot(snapshot_payload: dict[str, object]) -> StaticSnapshotReports:
    serialized_snapshot = serialize_snapshot(snapshot_payload)
    screenshot_bytes, mime_type = _screenshot_bytes(str(snapshot_payload["screenshot"]))
    serialized_snapshot["contrast_measurements"] = calculate_contrast_measurements(
        screenshot_bytes,
        serialized_snapshot["elements"],
    )
    runner = InMemoryRunner(agent=mobile_static_analysis_agent, app_name="mobile_static_analysis")
    session_id = await _run_agent(
        runner,
        # Keep large binary screenshot data out of the text prompt state.
        {str(MobileContextKey.NAVIGATOR_DATA): serialized_snapshot},
        _snapshot_content(screenshot_bytes, mime_type),
    )
    return await _snapshot_reports(runner, session_id)


def serialize_snapshot(snapshot_payload: dict[str, object]) -> dict[str, object]:
    """Validate and serialize the structured snapshot passed to LLM prompts."""
    elements = snapshot_payload.get("elements")
    if not isinstance(elements, list) or not elements:
        raise ValueError("Mobile static analysis requires at least one snapshot element.")
    if not str(snapshot_payload.get("activity") or "").strip():
        raise ValueError("Mobile static analysis requires a snapshot activity.")
    if not isinstance(snapshot_payload.get("screenshot"), str) or not snapshot_payload["screenshot"]:
        raise ValueError("Mobile static analysis requires a screenshot.")
    # The screenshot is sent as a multimodal part, not duplicated in the text context.
    return {key: value for key, value in snapshot_payload.items() if key != "screenshot"}


async def run_mobile_merge(deterministic_report: Report, contrast_report: Report, llm_report: Report) -> Report:
    runner = InMemoryRunner(agent=mobile_merge_agent, app_name="mobile_static_merge")
    session_id = await _run_agent(
        runner,
        {
            str(MobileContextKey.DETERMINISTIC_REPORT): deterministic_report.model_dump(mode="json"),
            str(MobileContextKey.CONTRAST_REPORT): contrast_report.model_dump(mode="json"),
            str(MobileContextKey.LLM_REPORT): llm_report.model_dump(mode="json"),
        },
        types.Content(role="user", parts=[types.Part(text="Merge the mobile accessibility reports now.")]),
    )
    return await _static_results(runner, session_id)


async def _run_agent(runner: InMemoryRunner, state: dict[str, object], content: types.Content) -> str:
    session_id = str(uuid4())
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="mobile_user",
        session_id=session_id,
        state=state,
    )
    async for _ in runner.run_async(user_id="mobile_user", session_id=session_id, new_message=content):
        pass
    return session_id


def _snapshot_content(screenshot_bytes: bytes, mime_type: str) -> types.Content:
    parts = [
        types.Part(text="Run mobile static analysis for the attached screenshot now."),
        types.Part.from_bytes(data=screenshot_bytes, mime_type=mime_type),
    ]
    return types.Content(role="user", parts=parts)


def _screenshot_bytes(screenshot: str) -> tuple[bytes, str]:
    path = Path(screenshot)
    try:
        if path.is_file():
            return path.read_bytes(), mimetypes.guess_type(path.name)[0] or "image/png"
    except OSError:
        pass
    # MobileSession stores screenshots as base64 until the scanner persists them.
    encoded_image = screenshot.split(",", 1)[1] if screenshot.startswith("data:image/") else screenshot
    try:
        return base64.b64decode(encoded_image, validate=True), "image/png"
    except ValueError as error:
        message = "Mobile static analysis received an invalid screenshot path or base64 image."
        raise ValueError(message) from error


async def _snapshot_reports(runner: InMemoryRunner, session_id: str) -> StaticSnapshotReports:
    session = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id="mobile_user",
        session_id=session_id,
    )
    if session is None:
        raise RuntimeError("Mobile static analysis session was not found.")
    return StaticSnapshotReports(
        contrast_report=_state_report(session.state, MobileContextKey.CONTRAST_REPORT),
        llm_report=_state_report(session.state, MobileContextKey.STATIC_RESULTS),
    )


async def _static_results(runner: InMemoryRunner, session_id: str) -> Report:
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
    return _report_from_value(result)


def _state_report(state: object, key: MobileContextKey) -> Report:
    if not isinstance(state, Mapping):
        raise TypeError("Mobile static analysis state must be a dictionary.")
    return _report_from_value(state.get(key) or state.get(str(key)))


def _report_from_value(value: object) -> Report:
    return Report.model_validate_json(value) if isinstance(value, str) else Report.model_validate(value)


def _report_with_screenshot(
    report: Report,
    screenshot_paths: object,
    snapshot_id: str,
) -> Report:
    screenshot_path = screenshot_paths.get(snapshot_id) if isinstance(screenshot_paths, Mapping) else None
    if not isinstance(screenshot_path, str) or not screenshot_path:
        return report
    issues = [issue.model_copy(update={"image_url_or_path": screenshot_path}) for issue in report.issue_list]
    return report.model_copy(update={"issue_list": issues})


async def _merge_activity_reports(
    analyses: list[SnapshotAnalysis],
    screenshot_paths: object,
) -> Report:
    total_snapshots = len(analyses)
    deterministic = merge_static_reports(
        [analysis.deterministic_report for analysis in analyses], total_snapshots, tool_name="deterministic"
    )
    contrast = merge_static_reports(
        [analysis.contrast_report for analysis in analyses], total_snapshots, tool_name="contrast_agent"
    )
    llm = merge_static_reports([analysis.llm_report for analysis in analyses], total_snapshots, tool_name="llm")
    if not deterministic.issue_list and not contrast.issue_list and not llm.issue_list:
        return merge_static_reports([], total_snapshots, tool_name="mobile")
    merged_report = await run_mobile_merge(deterministic, contrast, llm)
    return _merged_report_with_screenshots(merged_report, analyses, screenshot_paths)


def _merged_report_with_screenshots(
    report: Report,
    analyses: list[SnapshotAnalysis],
    screenshot_paths: object,
) -> Report:
    paths = screenshot_paths if isinstance(screenshot_paths, Mapping) else {}
    activity_screenshot = next(
        (path for analysis in analyses if isinstance(path := paths.get(analysis.snapshot_id), str) and path),
        None,
    )
    issues = [
        issue.model_copy(
            update={
                "image_url_or_path": _merged_issue_screenshot(
                    issue.html_snippet,
                    issue.image_url_or_path,
                    paths,
                    activity_screenshot,
                )
            }
        )
        for issue in report.issue_list
    ]
    return report.model_copy(update={"issue_list": issues})


def _merged_issue_screenshot(
    html_snippet: str,
    existing_screenshot: str | None,
    screenshot_paths: Mapping[object, object],
    activity_screenshot: str | None,
) -> str | None:
    snapshot = _SNAPSHOT_ID_PATTERN.search(html_snippet)
    snapshot_id = snapshot.group(1) if snapshot else None
    screenshot_path = screenshot_paths.get(snapshot_id)
    if isinstance(screenshot_path, str) and screenshot_path:
        return screenshot_path
    return existing_screenshot or activity_screenshot
