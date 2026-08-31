import logging

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import DUMMY_MODEL, ContextKey
from tools import AxeCoreTool

logger = logging.getLogger(__name__)


async def run_axe_core(tool_context: ToolContext) -> dict:
    """Run axe-core on the current page in BROWSER_SESSION and store report in state.

    Args:
        tool_context (ToolContext): The context for the tool execution, used to store results.

    Returns:
        dict: A confirmation message indicating that axe-core has completed and where the report is stored in the agent state.

    """
    logger.info("RunAxeAgent calling AxeCoreTool")
    result = (await AxeCoreTool().execute()).to_dict()

    tool_context.state[ContextKey.AXE_REPORT] = result
    analyzed_url = result.get("data", {}).get("url", "")
    return {"status": "axe_completed", "state_key": ContextKey.AXE_REPORT, "url_analyzed": analyzed_url}


axe_agent = LlmAgent(
    name="RunAxeAgent",
    model=DUMMY_MODEL,
    description="Run axe-core for the current page",
    instruction="Call `run_axe_core` once and return a brief confirmation.",
    tools=[run_axe_core],
)
