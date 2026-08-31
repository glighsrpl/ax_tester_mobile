"""ADK entrypoint for the mobile ax-tester agent."""

import logging

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, MobileContextKey
from mobile_tools.screen_scanner import MobileScreenScannerTool
from mobile_tools.utils.mobile_pipeline import (
    MobileStaticAnalyzer,
    activity_count,
    report_label,
    run_mobile_pipeline,
    state_string,
)
from mobile_tools.utils.report_utils import (
    flatten_issues_by_activity,
    save_source_reports,
)
from mobile_tools.utils.session import MOBILE_SESSION
from mobile_tools.saver_tool import generate_run_timestamp
from utils.report_store import REPORTS_ROOT

MAX_CONCURRENT_STATIC_ANALYSES = 4
logger = logging.getLogger(__name__)

__all__ = ["flatten_issues_by_activity", "mobile_root_agent", "run_mobile_test"]


MOBILE_ROOT_AGENT_INSTRUCTION = """
You are the root orchestrator for Android mobile accessibility testing.

Use only this tool:
- `run_mobile_test(max_steps, max_activities, max_depth)`

Rules:
1. The Android app target is provided by the caller.
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
    app_package = state_string(tool_context.state, MobileContextKey.APP_PACKAGE)
    app_activity = state_string(tool_context.state, MobileContextKey.APP_ACTIVITY)
    capability_id = state_string(tool_context.state, MobileContextKey.CAPABILITY_ID)
    platform = state_string(tool_context.state, MobileContextKey.PLATFORM)
    if not app_package or not app_activity or not capability_id or platform not in {"Android", "iOS"}:
        raise ValueError("Missing mobile app package, activity, capability id, or supported platform.")

    resolved_max_steps = max(int(max_steps), 1)
    resolved_max_activities = max(int(max_activities), 1)
    resolved_max_depth = max(int(max_depth), 0)
    tool_context.state[MobileContextKey.MAX_STEPS] = resolved_max_steps
    tool_context.state[MobileContextKey.MAX_ACTIVITIES] = resolved_max_activities
    tool_context.state[MobileContextKey.MAX_DEPTH] = resolved_max_depth

    await MOBILE_SESSION.connect(capability_id, app_package=app_package, app_activity=app_activity)
    page_source = await MOBILE_SESSION.get_accessibility_tree()
    serial = capability_id.removeprefix("local-android:")
    if not page_source or len(page_source) < 100:
        raise RuntimeError(f"Empty UI tree from device {serial}, session may not be ready")

    try:
        report_id = f"{generate_run_timestamp()}_{report_label(app_package)}"
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
        navigator_data, static_analysis = await run_mobile_pipeline(
            navigator,
            MobileStaticAnalyzer(platform),
            MAX_CONCURRENT_STATIC_ANALYSES,
        )
        navigator_data["report_id"] = report_id
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
        "activities": activity_count(navigator_data),
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
