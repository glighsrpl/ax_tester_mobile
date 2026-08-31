from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, ContextKey
from schemas import Report
from tools import ImageAnalyzerTool
from tools.base import ToolResult


async def analyze_images_in_webpage(tool_context: ToolContext) -> dict:
    """Analyze images on the current page for alt text issues and store results in state.

    Args:
        tool_context (ToolContext): The context for the tool execution, used to store results.

    Returns:
        dict: A confirmation message indicating the number of images analyzed and issues found.

    """
    raw: ToolResult = await ImageAnalyzerTool().execute()
    data = raw.data if isinstance(raw.data, dict) else {}
    issue_list = data.get("issue_list", [])
    page_url = data.get("page", "")

    report = Report.model_validate(
        {
            "tool_name": raw.tool_name,
            "issue_list": issue_list,
            "total_issues": len(issue_list),
            "page": page_url,
            "score_passed": raw.score_passed,
            "score_total": raw.score_total,
            "metadata": [
                {"key": "status", "value": raw.status.value},
                {"key": "error", "value": raw.error or ""},
                {"key": "skipped", "value": data.get("skipped", 0)},
                {"key": "decorative", "value": data.get("decorative", 0)},
            ],
        }
    ).model_dump()
    tool_context.state[ContextKey.IMAGE_ANALYZER_REPORT] = report

    return {
        "status": "success" if raw.status.value == "success" else "failure",
        "message": f"Analyzed {len(issue_list)} image issues on {page_url}.",
        "state_key": ContextKey.IMAGE_ANALYZER_REPORT,
    }


image_analyzer_agent = LlmAgent(
    name="ImageAnalyzer",
    model=MODEL,
    description="Analyzes images in a webpage and ensures they have consistent alt text.",
    instruction="Call `analyze_images_in_webpage` once and return a brief confirmation.",
    tools=[analyze_images_in_webpage],
)
