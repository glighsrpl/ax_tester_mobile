from google.adk.tools.tool_context import ToolContext

from common import MobileContextKey
from mobile_tools.keyboard_scanner import MobileKeyboardScannerTool


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


async def run_mobile_keyboard_navigation(tool_context: ToolContext) -> dict[str, object]:
    """Collect keyboard-navigation evidence without running accessibility analysis."""
    max_steps = _state_int(tool_context, MobileContextKey.MAX_STEPS, 10)
    result = await MobileKeyboardScannerTool({"step_budget": max_steps}).execute()
    if not result.is_success():
        raise RuntimeError(result.error or "Mobile keyboard navigation failed.")
    tool_context.state[MobileContextKey.KEYBOARD_NAVIGATION_DATA] = result.data
    return {"status": "success", "steps": result.data.get("total_steps", 0)}
