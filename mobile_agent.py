"""ADK entrypoint for the mobile accessibility-testing agent."""

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from tools.mobile_accessibility_service import (
    MobileAccessibilityScanRequest,
    run_mobile_accessibility_scan,
)

MOBILE_ROOT_AGENT_INSTRUCTION = """
You are the root orchestrator for mobile accessibility testing.

Use only this tool:
- `run_mobile_test(max_steps, max_activities, max_depth)`

Rules:
1. The mobile app target is provided by the caller.
2. Call `run_mobile_test` exactly once.
3. Do not ask for confirmations.
4. Return a short summary with tested activities.
"""


async def run_mobile_test(
    tool_context: ToolContext,
    max_steps: int = 500,
    max_activities: int = 3,
    max_depth: int = 5,
) -> dict[str, object]:
    """Run the mobile scan using the target and capability in ADK state."""
    request = MobileAccessibilityScanRequest(
        app_package=_state_string(tool_context, MobileContextKey.APP_PACKAGE),
        app_activity=_state_string(tool_context, MobileContextKey.APP_ACTIVITY),
        capability_id=_state_string(tool_context, MobileContextKey.CAPABILITY_ID),
        platform=_state_string(tool_context, MobileContextKey.PLATFORM),
        max_steps=max_steps,
        max_activities=max_activities,
        max_depth=max_depth,
    ).normalized()
    _store_navigation_limits(tool_context, request)

    scan_result = await run_mobile_accessibility_scan(request)
    tool_context.state[MobileContextKey.NAVIGATOR_DATA] = scan_result.navigator_data
    tool_context.state[MobileContextKey.STATIC_RESULTS] = scan_result.static_results
    tool_context.state[MobileContextKey.STATIC_DEBUG_DATA] = scan_result.static_debug_data
    return {
        "status": "success",
        "activities": scan_result.activities,
        "final_response": "Mobile navigation and static analysis completed.",
        "static_results": scan_result.static_results,
    }


def _state_string(tool_context: ToolContext, key: MobileContextKey) -> str:
    value = tool_context.state.get(key, tool_context.state.get(str(key), ""))
    return str(value).strip() if value else ""


def _store_navigation_limits(
    tool_context: ToolContext,
    request: MobileAccessibilityScanRequest,
) -> None:
    tool_context.state[MobileContextKey.MAX_STEPS] = request.max_steps
    tool_context.state[MobileContextKey.MAX_ACTIVITIES] = request.max_activities
    tool_context.state[MobileContextKey.MAX_DEPTH] = request.max_depth


mobile_root_agent = LlmAgent(
    name="MobileRootAgent",
    model=MODEL,
    description="Orchestrates mobile accessibility testing.",
    instruction=MOBILE_ROOT_AGENT_INSTRUCTION,
    tools=[run_mobile_test],
)
