import logging
from pathlib import Path
from typing import Any

import yaml
from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools.tool_context import ToolContext

from common import MODEL, ContextKey
from utils.browser_session import BROWSER_SESSION
from utils.html_sanitizer import sanitize_html_for_llm

logger = logging.getLogger(__name__)


def set_wcag_level(tool_context: ToolContext, level: str = "AA") -> dict[str, Any]:
    """Set the active WCAG level set for the loop audit.

    Accepts: A (Level A only), AA (Levels A and AA), AAA (Levels A, AA and AAA).
    """
    logger.info("Setting WCAG level info")

    normalized = level.strip().upper()
    if normalized not in ["A", "AA", "AAA"]:
        raise ValueError("wcag level must be one of: A, AA, AAA")

    tool_context.state[ContextKey.COMPLIANCE_LEVEL] = normalized

    ROOT_DIR = Path(__file__).resolve().parents[2]
    with open(ROOT_DIR / "prompts" / "wcag.yml", encoding="utf-8") as f:
        wcag_data = yaml.safe_load(f)
    levels = wcag_data.get("levels") or {}
    for lev in range(len(normalized) + 1, 4):
        levels.pop("A" * lev, None)
    wcag_data["levels"] = levels

    tool_context.state[ContextKey.WCAG_PROMPT] = yaml.safe_dump(wcag_data)

    return {"status": "set", "wcag_level": level}


async def fetch_dom_html(tool_context: ToolContext) -> dict[str, Any]:
    """Fetch the HTML DOM from the current shared browser page and store it."""
    logger.info("Fetching DOM and saving HTML in ToolContext state")

    if not BROWSER_SESSION.is_initialized():
        raise RuntimeError(
            "Browser session not initialized. Initialize and navigate with root tools before fetching DOM."
        )

    raw_html, page_url = await BROWSER_SESSION.get_page_html()

    clean_html, _ = sanitize_html_for_llm(raw_html)

    tool_context.state[ContextKey.DOM_HTML] = clean_html
    return {"status": "fetched", "state_name": ContextKey.DOM_HTML, "url": page_url}


init_agent = LlmAgent(
    name="InitAgent",
    model=MODEL,
    description="Initialize common data",
    instruction="Call `set_wcag_level` and `fetch_dom_html` to prepare data.",
    tools=[set_wcag_level, fetch_dom_html],
)
