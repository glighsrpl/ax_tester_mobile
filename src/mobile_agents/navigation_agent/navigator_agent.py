from google.adk.agents.llm_agent import LlmAgent

from common import MODEL
from mobile_tools.agent_tools import run_mobile_guided_navigation, run_mobile_screen_scan

MOBILE_NAVIGATOR_INSTRUCTION = """
You are the Android mobile navigator, with the ability to scan app screens in order to test accessibility and follow explicit navigation instructions.

Rules:
1. If explicit navigation instructions are provided, call `run_mobile_guided_navigation` once with them.
2. Otherwise call directly `run_mobile_screen_scan` once.
3. Never tap controls unless the instructions explicitly ask for it.
4. Return only a brief confirmation.
"""

mobile_navigator_agent = LlmAgent(
    name="MobileNavigatorAgent",
    model=MODEL,
    description="Scans Android app screens and follows explicit navigation instructions.",
    instruction=MOBILE_NAVIGATOR_INSTRUCTION,
    tools=[run_mobile_screen_scan, run_mobile_guided_navigation],
)
