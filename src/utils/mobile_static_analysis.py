import base64
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from google.adk.runners import InMemoryRunner
from google.genai import types

from common import MobileContextKey
from mobile_agents.static_agent import (
    mobile_merge_agent,
    mobile_static_analysis_agent,
    mobile_static_post_pass_agent,
)
from schemas import Report, ScoreInfo
from tools.mobile_screen_scanner import MobileScanSnapshot
from utils.contrast_calculator import calculate_contrast_measurements
from utils.mobile_queue import SnapshotAnalysis
from utils.mobile_report import merge_static_reports


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
    *,
    page: str,
) -> tuple[Report, Report, Report]:
    """Prepare complete source reports with the screenshot of every finding."""
    total_snapshots = len(analyses)
    deterministic = _aggregate_source_report(
        [
            _report_with_screenshot(analysis.deterministic_report, screenshot_paths, analysis.snapshot_id)
            for analysis in analyses
        ],
        total_snapshots,
        "deterministic",
    )
    contrast = _aggregate_source_report(
        [
            _report_with_screenshot(analysis.contrast_report, screenshot_paths, analysis.snapshot_id)
            for analysis in analyses
        ],
        total_snapshots,
        "contrast_agent",
    )
    llm = _aggregate_source_report(
        [
            _report_with_screenshot(analysis.llm_report, screenshot_paths, analysis.snapshot_id)
            for analysis in analyses
        ],
        total_snapshots,
        "llm",
    )
    return tuple(report.model_copy(update={"page": page}) for report in (deterministic, contrast, llm))


async def run_static_snapshot(snapshot_payload: dict[str, object], platform: str) -> StaticSnapshotReports:
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
        {
            str(MobileContextKey.NAVIGATOR_DATA): serialized_snapshot,
            str(MobileContextKey.PLATFORM): platform,
        },
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


async def run_cross_screen_analysis(
    screen_summaries: list[dict[str, object]],
    app_package: str,
    activity: str,
) -> Report:
    """Run the Static Agent's one-time cross-screen post-pass."""
    runner = InMemoryRunner(agent=mobile_static_post_pass_agent, app_name="mobile_static_cross_screen")
    session_id = await _run_agent(
        runner,
        {
            str(MobileContextKey.CROSS_SCREEN_REPORT): screen_summaries,
            str(MobileContextKey.APP_PACKAGE): app_package,
            str(MobileContextKey.APP_ACTIVITY): activity,
        },
        types.Content(role="user", parts=[types.Part(text="Run the cross-screen static analysis now.")]),
    )
    report = await _state_report_for_key(runner, session_id, MobileContextKey.CROSS_SCREEN_REPORT)
    return report.model_copy(update={"page": mobile_page(app_package, activity)})


async def run_mobile_merge(
    deterministic_report: Report,
    contrast_report: Report,
    llm_report: Report,
) -> Report:
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
    return await _state_report_for_key(runner, session_id, MobileContextKey.STATIC_RESULTS)


async def _state_report_for_key(
    runner: InMemoryRunner,
    session_id: str,
    key: MobileContextKey,
) -> Report:
    session = await runner.session_service.get_session(
        app_name=runner.app_name,
        user_id="mobile_user",
        session_id=session_id,
    )
    result = session.state.get(key) or session.state.get(str(key)) if session else None
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


def _aggregate_source_report(reports: list[Report], total_snapshots: int, tool_name: str) -> Report:
    """Combine reports without deduplicating findings before the merge agent."""
    report_buckets = {str(index): report.issue_list for index, report in enumerate(reports)}
    return merge_static_reports(reports, total_snapshots, report_buckets, tool_name)


def append_cross_screen_issues(merge_report: Report, cross_screen_report: Report) -> Report:
    """Create the final report by appending cross-screen findings without deduplication."""
    issues = [*merge_report.issue_list, *cross_screen_report.issue_list]
    return merge_report.model_copy(
        update={
            "issue_list": issues,
            "total_issues": len(issues),
            "score_total": _sum_score_info(merge_report.score_total, cross_screen_report.score_total),
            "score_passed": _sum_score_info(merge_report.score_passed, cross_screen_report.score_passed),
        }
    )


def _sum_score_info(first: ScoreInfo, second: ScoreInfo) -> ScoreInfo:
    return ScoreInfo(
        level_A=first.level_A + second.level_A,
        level_AA=first.level_AA + second.level_AA,
        level_AAA=first.level_AAA + second.level_AAA,
    )


def mobile_page(app_package: str, activity: str) -> str:
    return f"mobile://{app_package}/{activity}"
