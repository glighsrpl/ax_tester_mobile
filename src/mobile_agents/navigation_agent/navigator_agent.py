from google.adk.agents.llm_agent import LlmAgent

from common import MODEL
from mobile_tools.agent_tools import run_mobile_screen_scan

MOBILE_NAVIGATOR_INSTRUCTION = """
You are the Android mobile navigator, with the ability to scan app screens for accessibility testing.

Rules:
1. Call `run_mobile_screen_scan` once.
2. Return only a brief confirmation.
"""

mobile_navigator_agent = LlmAgent(
    name="MobileNavigatorAgent",
    model=MODEL,
    description="Scans Android app screens for accessibility testing.",
    instruction=MOBILE_NAVIGATOR_INSTRUCTION,
    tools=[run_mobile_screen_scan],
)
