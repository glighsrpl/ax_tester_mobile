import base64
import mimetypes
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from google.adk.runners import InMemoryRunner
from google.genai import types

from common import MobileContextKey
from mobile_agents.static_agent import mobile_merge_agent, mobile_static_analysis_agent
from schemas import Report


@dataclass(frozen=True)
class StaticSnapshotReports:
    """Reports emitted by the visual and static sub-agents for one snapshot."""

    contrast_report: Report
    llm_report: Report


async def run_static_snapshot(snapshot_payload: dict[str, object]) -> StaticSnapshotReports:
    serialized_snapshot = serialize_snapshot(snapshot_payload)
    runner = InMemoryRunner(agent=mobile_static_analysis_agent, app_name="mobile_static_analysis")
    session_id = await _run_agent(
        runner,
        # Keep large binary screenshot data out of the text prompt state.
        {str(MobileContextKey.NAVIGATOR_DATA): serialized_snapshot},
        _snapshot_content(snapshot_payload),
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


def _snapshot_content(snapshot_payload: dict[str, object]) -> types.Content:
    screenshot_path = snapshot_payload.get("screenshot")
    if not isinstance(screenshot_path, str) or not screenshot_path:
        raise ValueError("Mobile static analysis requires a screenshot.")
    parts = [
        types.Part(text="Run mobile static analysis for the attached screenshot now."),
        _screenshot_part(screenshot_path),
    ]
    return types.Content(role="user", parts=parts)


def _screenshot_part(screenshot_path: str) -> types.Part:
    screenshot_bytes, mime_type = _screenshot_bytes(screenshot_path)
    return types.Part.from_bytes(data=screenshot_bytes, mime_type=mime_type)


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
