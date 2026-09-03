import asyncio
from typing import Any

from dotenv import load_dotenv

from common import MobileContextKey
from mcp_server import MobileAgentBridge, _detect_mobile_platform, _report_embedded_content, read_report_json
from tools.mobile_saver_tool import run_save_mobile
from utils.mobile_capabilities import discover_mobile_capabilities

load_dotenv()


def _error_result(message: str, details: dict) -> dict:
    return {
        "status": "error",
        "message": message,
        "details": details,
    }


def _build_mobile_scan_result(bridge_result: dict[str, Any]):
    report_artifact = bridge_result.get("report_artifact")
    if not isinstance(report_artifact, dict) or not report_artifact.get("report_id"):
        return _error_result(
            "The accessibility test completed without a saved report artifact.",
            {
                "session_id": bridge_result.get("session_id"),
                "current_url": bridge_result.get("current_url"),
                "final_response": bridge_result.get("final_response", ""),
            },
        )

    report_id = report_artifact["report_id"]

    try:
        content, json_metadata = _report_embedded_content(
            report_id,
            "json",
            f"Accessibility test completed. Report id: {report_id}. JSON report attached.",
        )
        report = read_report_json(report_id)
        print(f"Report {report_id} loaded successfully. Report summary: {report.get('summary', {})}")
    except (FileNotFoundError, ValueError, OSError) as exc:
        return _error_result(
            f"The test saved report_id {report_id}, but the JSON report could not be loaded: {exc}",
            {
                "session_id": bridge_result.get("session_id"),
                "current_url": bridge_result.get("current_url"),
                "report_id": report_id,
                "report_artifact": report_artifact,
            },
        )


async def run_full_mobile_test(
    app_package: str,
    app_activity: str,
    capability_id: str | None = None,
    max_steps: int = 5,
    max_activities: int = 20,
    max_depth: int = 10,
):
    """Run the mobile accessibility flow using explicit app package/activity arguments.

    Parameters:
        app_package: Required. The package name of the target mobile application to test.
        app_activity: Required. The main activity of the target mobile application to test.
        capability_id: Optional. The ID of the mobile device capability to use for testing.
            If not provided, the tool will attempt to discover a single available capability.
        max_steps: Optional. The maximum number of steps to perform during the test.
        max_activities: Optional. The maximum number of unique activities to visit during the test.
        max_depth: Optional. The maximum navigation depth from the initial mobile screen.
    Only `app_package` and `app_activity` are required.
    Optional arguments should be supplied only when the caller wants to override the documented defaults,
    although MCP clients may still include default-valued arguments in the tool call.
    """
    app_package = app_package.strip()
    app_activity = app_activity.strip().lstrip("/")
    capability_id = capability_id.strip() if capability_id else None
    if not app_package or not app_activity:
        return _error_result("app_package and app_activity are required.", {})

    capabilities = discover_mobile_capabilities()
    if capability_id is None:
        if len(capabilities) != 1:
            return _error_result(
                "Expected exactly one local mobile capability. Pass capability_id explicitly.",
                {"capabilities": capabilities},
            )
        capability_id = str(capabilities[0]["id"])

    try:
        platform = _detect_mobile_platform(capabilities, capability_id)
        bridge_result = await mobile_bridge.run_turn(
            {
                str(MobileContextKey.APP_PACKAGE): app_package,
                str(MobileContextKey.APP_ACTIVITY): app_activity,
                str(MobileContextKey.CAPABILITY_ID): capability_id,
                str(MobileContextKey.PLATFORM): platform,
                str(MobileContextKey.MAX_STEPS): max_steps,
                str(MobileContextKey.MAX_ACTIVITIES): max_activities,
                str(MobileContextKey.MAX_DEPTH): max_depth,
            }
        )
        bridge_result["report_artifact"] = run_save_mobile(bridge_result.get("state", {}))
        bridge_result["current_url"] = f"mobile://{app_package}/{app_activity}"
        return _build_mobile_scan_result(bridge_result)
    except Exception as exc:
        return _error_result(str(exc), {"capability_id": capability_id})


if __name__ == "__main__":
    mobile_bridge = MobileAgentBridge()
    asyncio.run(
        run_full_mobile_test(
            app_package="it.widiba.bol",
            app_activity=".MainActivity",
            capability_id=None,
            max_steps=1,
            max_activities=20,
            max_depth=10,
        )
    )
