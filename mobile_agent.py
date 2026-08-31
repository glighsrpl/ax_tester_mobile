"""ADK entrypoint for the mobile ax-tester agent."""

import logging
from uuid import uuid4

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.runners import InMemoryRunner, Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.adk.utils.context_utils import Aclosing
from google.genai import types

from common import MODEL, ContextKey
from mobile_agents.navigation_agent import mobile_navigator_agent
from mobile_agents.static_agent import mobile_static_analysis_agent
from mobile_tools.utils.session import MOBILE_SESSION
from schemas import Report

logger = logging.getLogger(__name__)

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
    app_package = _state_str(tool_context, ContextKey.MOBILE_APP_PACKAGE)
    app_activity = _state_str(tool_context, ContextKey.MOBILE_APP_ACTIVITY)
    capability_id = _state_str(tool_context, ContextKey.MOBILE_CAPABILITY_ID)
    if not app_package or not app_activity or not capability_id:
        raise ValueError("Missing mobile app package, activity, or capability id.")

    resolved_max_steps = max(int(max_steps), 1)
    resolved_max_activities = max(int(max_activities), 1)
    resolved_max_depth = max(int(max_depth), 0)
    resolved_instructions = instructions.strip() or _state_str(tool_context, ContextKey.MOBILE_INSTRUCTIONS)
    tool_context.state[ContextKey.MOBILE_MAX_STEPS] = resolved_max_steps
    tool_context.state[ContextKey.MOBILE_MAX_ACTIVITIES] = resolved_max_activities
    tool_context.state[ContextKey.MOBILE_MAX_DEPTH] = resolved_max_depth
    tool_context.state[ContextKey.MOBILE_INSTRUCTIONS] = resolved_instructions

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
        str(ContextKey.MOBILE_APP_PACKAGE): app_package,
        str(ContextKey.MOBILE_APP_ACTIVITY): app_activity,
        str(ContextKey.MOBILE_CAPABILITY_ID): capability_id,
        str(ContextKey.MOBILE_MAX_STEPS): resolved_max_steps,
        str(ContextKey.MOBILE_MAX_ACTIVITIES): resolved_max_activities,
        str(ContextKey.MOBILE_MAX_DEPTH): resolved_max_depth,
        str(ContextKey.MOBILE_INSTRUCTIONS): resolved_instructions,
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
    navigator_data = state.get(ContextKey.MOBILE_NAVIGATOR_DATA) or state.get(
        str(ContextKey.MOBILE_NAVIGATOR_DATA)
    )
    if isinstance(navigator_data, dict):
        tool_context.state[ContextKey.MOBILE_NAVIGATOR_DATA] = navigator_data

    # Run static accessibility analysis on the collected snapshots and store results
    static_report = await _run_static_analysis(navigator_data)
    static_results = static_report.model_dump(mode="json")
    tool_context.state[ContextKey.MOBILE_STATIC_RESULTS] = static_results

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


def _state_str(tool_context: ToolContext, key: ContextKey) -> str:
    return str(tool_context.state.get(key) or tool_context.state.get(str(key)) or "").strip()


def _activity_count(data: dict[str, object]) -> int:
    activities = data.get("visited_activities") or []
    return len(activities) if isinstance(activities, list) else 0


async def _run_static_analysis(navigator_data: object) -> Report:
    raw_snapshots = navigator_data.get("snapshots") if isinstance(navigator_data, dict) else None
    if not isinstance(raw_snapshots, list) or not raw_snapshots:
        logger.warning("Mobile navigator returned no snapshots; skipping static analysis")
        return _empty_static_report()

    runner = InMemoryRunner(agent=mobile_static_analysis_agent, app_name="mobile_static_analysis")
    session_id = str(uuid4())
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="mobile_user",
        session_id=session_id,
        state={str(ContextKey.MOBILE_NAVIGATOR_DATA): navigator_data},
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
    result = session.state.get(ContextKey.MOBILE_STATIC_RESULTS) if session else None
    return Report.model_validate_json(result) if isinstance(result, str) else Report.model_validate(result)


def _empty_static_report() -> Report:
    return Report(
        tool_name="mobile-static",
        total_issues=0,
        page="mobile",
        issue_list=[],
        metadata=[{"key": "snapshots", "value": 0}],
    )
