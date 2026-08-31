from uuid import uuid4

from google.adk.runners import InMemoryRunner
from google.genai import types

from common import MobileContextKey
from mobile_agents.static_agent import mobile_merge_agent, mobile_static_analysis_agent
from schemas import Report


async def run_static_snapshot(snapshot_payload: dict[str, object]) -> Report:
    runner = InMemoryRunner(agent=mobile_static_analysis_agent, app_name="mobile_static_analysis")
    session_id = await _run_agent(
        runner,
        {str(MobileContextKey.NAVIGATOR_DATA): snapshot_payload},
        "Run mobile static analysis now.",
    )
    return await _static_results(runner, session_id)


async def run_mobile_merge(deterministic_report: Report, llm_report: Report) -> Report:
    runner = InMemoryRunner(agent=mobile_merge_agent, app_name="mobile_static_merge")
    session_id = await _run_agent(
        runner,
        {
            str(MobileContextKey.DETERMINISTIC_REPORT): deterministic_report.model_dump(mode="json"),
            str(MobileContextKey.LLM_REPORT): llm_report.model_dump(mode="json"),
        },
        "Merge the mobile accessibility reports now.",
    )
    return await _static_results(runner, session_id)


async def _run_agent(runner: InMemoryRunner, state: dict[str, object], message: str) -> str:
    session_id = str(uuid4())
    await runner.session_service.create_session(
        app_name=runner.app_name,
        user_id="mobile_user",
        session_id=session_id,
        state=state,
    )
    content = types.Content(role="user", parts=[types.Part(text=message)])
    async for _ in runner.run_async(user_id="mobile_user", session_id=session_id, new_message=content):
        pass
    return session_id


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
    return Report.model_validate_json(result) if isinstance(result, str) else Report.model_validate(result)
