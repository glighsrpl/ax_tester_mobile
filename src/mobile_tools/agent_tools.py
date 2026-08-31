from typing import Any

from google.adk.tools.tool_context import ToolContext

from common import MobileContextKey
from mobile_tools.guided_navigator import MobileGuidedNavigatorTool
from mobile_tools.screen_scanner import MobileScreenScannerTool
from tools.base import ToolResult


def _state_str(tool_context: ToolContext, key: MobileContextKey, default: str = "") -> str:
    return str(tool_context.state.get(key) or tool_context.state.get(str(key)) or default).strip()


def _state_int(tool_context: ToolContext, key: MobileContextKey, default: int) -> int:
    value = tool_context.state.get(key)
    if value is None:
        value = tool_context.state.get(str(key))
    if value is None:
        value = default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _activity_count(data: dict[str, Any]) -> int:
    return len(data.get("visited_activities") or [])


async def _scan(app_package: str, max_steps: int, max_activities: int, max_depth: int) -> dict[str, Any]:
    raw_result: ToolResult = await MobileScreenScannerTool(
        {
            "max_steps": max_steps,
            "max_activities": max_activities,
            "max_depth": max_depth,
            "target_app_package": app_package,
        }
    ).execute()
    if not raw_result.is_success():
        raise RuntimeError(raw_result.error or "Mobile screen scan failed.")
    return raw_result.data


async def run_mobile_screen_scan(tool_context: ToolContext) -> dict[str, Any]:
    """
    Run a mobile screen scan using the MobileScreenScannerTool and return the scan results.

    Attributes:
        tool_context (ToolContext): The context containing the state and configuration for the tool execution.
            app_package (str): The package name of the target mobile application to scan.
            max_steps (int): The maximum number of steps to perform during the scan.
            max_activities (int): The maximum number of unique activities to visit during the scan.
            max_depth (int): The maximum navigation depth from the initial screen.

    Returns:
        dict[str, Any]: A dictionary containing the scan results, including the status and the number of activities visited during the scan.
    """
    app_package = _state_str(tool_context, MobileContextKey.APP_PACKAGE)
    max_steps = _state_int(tool_context, MobileContextKey.MAX_STEPS, 10)
    max_activities = _state_int(tool_context, MobileContextKey.MAX_ACTIVITIES, 10)
    max_depth = _state_int(tool_context, MobileContextKey.MAX_DEPTH, 5)
    data = await _scan(app_package, max_steps, max_activities, max_depth)
    tool_context.state[MobileContextKey.NAVIGATOR_DATA] = data
    return {"status": "success", "activities": _activity_count(data)}


async def run_mobile_guided_navigation(
    tool_context: ToolContext,
    instructions: str = "",
) -> dict[str, Any]:
    """
    Run a mobile guided navigation using the MobileGuidedNavigatorTool and return the navigation results.

    Attributes:
        tool_context (ToolContext): The context containing the state and configuration for the tool execution.
            app_package (str): The package name of the target mobile application to navigate.
            max_steps (int): The maximum number of steps to perform during the navigation.
            instructions (str): The navigation instructions to guide the navigation process.
    """
    app_package = _state_str(tool_context, MobileContextKey.APP_PACKAGE)
    max_steps = _state_int(tool_context, MobileContextKey.MAX_STEPS, 10)
    max_activities = _state_int(tool_context, MobileContextKey.MAX_ACTIVITIES, 10)
    max_depth = _state_int(tool_context, MobileContextKey.MAX_DEPTH, 5)
    text = instructions.strip() or _state_str(tool_context, MobileContextKey.INSTRUCTIONS)
    raw_result: ToolResult = await MobileGuidedNavigatorTool(
        {
            "instructions": text,
            "max_steps": max_steps,
        }
    ).execute()
    if not raw_result.is_success():
        raise RuntimeError(raw_result.error or "Mobile guided navigation failed.")

    data = await _scan(app_package, max_steps, max_activities, max_depth)
    guided_path = raw_result.data.get("path", []) if isinstance(raw_result.data, dict) else []
    data["path"] = [*guided_path, *data.get("path", [])]
    tool_context.state[MobileContextKey.NAVIGATOR_DATA] = data
    return {"status": "success", "activities": _activity_count(data)}
