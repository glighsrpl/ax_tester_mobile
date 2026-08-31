from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, ContextKey
from schemas import Report, ScoreInfo
from tools import RuntimeNavigatorTool
from tools.base import ToolResult


async def analyze_runtime_navigation(tool_context: ToolContext, max_steps: int = 200) -> dict:
    """Run runtime navigation on the current page and store results in agent state."""
    raw_result: ToolResult = await RuntimeNavigatorTool({"max_steps": max_steps}).execute()
    result: dict = raw_result.to_dict()
    data = result.get("data", {})
    page_url = data.get("page_url", "")
    page_screenshot = data.get("page_screenshot")
    if page_screenshot:
        tool_context.state[ContextKey.PAGE_SCREENSHOT] = page_screenshot

    consumer_results = data.get("consumer_results", []) or []
    updated_keys = []
    for consumer_result in consumer_results:
        report_key = consumer_result.get("report_key")
        consumer_result_data = consumer_result.get("result", {})
        issue_list = consumer_result_data.get("issue_list", []) or []
        if not report_key:
            continue
        report_dict = Report.model_validate(
            {
                "tool_name": consumer_result_data.get("name"),
                "issue_list": issue_list,
                "total_issues": len(issue_list),
                "page": page_url,
                "score_passed": consumer_result_data.get("score_passed", ScoreInfo()),
                "score_total": consumer_result_data.get("score_total", ScoreInfo()),
                "metadata": [
                    {"key": "checked", "value": int(consumer_result_data.get("checked", 0) or 0)},
                ],
            }
        ).model_dump()

        tool_context.state[report_key] = report_dict
        updated_keys.append(report_key)

    return {
        "status": "success" if result["status"] == "success" else "failure",
        "message": f"Runtime navigation completed on {page_url}. Updated reports: {updated_keys}.",
    }


navigator_agent = LlmAgent(
    name="RuntimeNavigatorAgent",
    model=MODEL,
    description="Runs runtime navigation and aggregates consumer findings.",
    instruction="Call `analyze_runtime_navigation` once and return a brief confirmation.",
    tools=[analyze_runtime_navigation],
)
