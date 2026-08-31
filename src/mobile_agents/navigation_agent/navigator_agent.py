from google.adk.agents.llm_agent import LlmAgent

from common import MODEL
from tools.mobile_agent_tools import run_mobile_keyboard_navigation

MOBILE_NAVIGATOR_INSTRUCTION = """
You collect keyboard-navigation evidence for mobile accessibility testing.

Rules:
1. Call `run_mobile_keyboard_navigation` once.
2. Return only a brief confirmation.
"""

mobile_keyboard_navigator_agent = LlmAgent(
    name="MobileKeyboardNavigatorAgent",
    model=MODEL,
    description="Collects mobile keyboard-navigation evidence.",
    instruction=MOBILE_NAVIGATOR_INSTRUCTION,
    tools=[run_mobile_keyboard_navigation],
)
