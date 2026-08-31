"""ADK entrypoint for the ax-tester agent.

This file exposes root_agent for ADK discovery while keeping the implementation
inside src/agents.
"""

# ruff: noqa: E402

import logging
from collections import deque
from urllib.parse import urlparse
from uuid import uuid4

from dotenv import load_dotenv

load_dotenv()

from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.tools.tool_context import ToolContext
from google.adk.utils.context_utils import Aclosing
from google.genai import types

from agents.navigation_agent import navigator_agent
from agents.semantic_agent import image_analyzer_agent
from agents.static_agent import static_analysis_agent
from common import DUMMY_MODEL, MODEL, ContextKey
from tools.saver_tool import generate_run_timestamp, run_save, write_run_results_index
from utils.browser_session import BROWSER_SESSION
from utils.site_crawler import collect_links_from_current_page, normalize_url

logger = logging.getLogger(__name__)

ROOT_AGENT_INSTRUCTION = """
You are the root orchestrator for accessibility testing.

Use only this tool for tests:
- `run_crawl_test(url, max_depth, max_pages, same_host_only)`

Execution policy:
1. Extract the target URL from the user request.
2. If no URL is provided, ask one concise follow-up question requesting it, then stop.
3. Always run tests by calling `run_crawl_test`.
4. Use user-provided crawl parameters when present; otherwise use defaults:
   - `max_depth=0`
   - `max_pages=10`
   - `same_host_only=true`
5. Return a short summary with root URL, visited pages, max depth, and whether `max_pages` was reached.

Rules:
- Do not use alternate testing flows.
- Call `run_crawl_test` exactly once per request.
"""


async def _run_tester_once(
    runner: Runner,
    session_service: InMemorySessionService,
    page_url: str,
    crawl_folder_name: str,
) -> dict[str, str]:
    """Run AccessibilityTesterAgent once against the current page in BROWSER_SESSION."""

    logger.info(f"Running AccessibilityTesterAgent on {page_url}")

    session_id = str(uuid4())
    await session_service.create_session(
        app_name="ax_tester_crawl_internal",
        user_id="crawl_user",
        session_id=session_id,
        state={ContextKey.CRAWL_FOLDER_NAME: crawl_folder_name},
    )

    content = types.Content(
        role="user",
        parts=[
            types.Part(
                text=(
                    f"Run the accessibility test now on the currently open page {page_url}. "
                    "Use your standard sequence and save results."
                )
            )
        ],
    )

    final_response = ""
    async with Aclosing(
        runner.run_async(
            user_id="crawl_user",
            session_id=session_id,
            new_message=content,
        )
    ) as event_stream:
        async for event in event_stream:
            if event.content and event.content.parts:
                text = "".join(part.text or "" for part in event.content.parts).strip()
                if text and (event.author or "").lower() != "user":
                    final_response = text

    return {"status": "ok", "final_response": final_response}


def _extract_root_host_label(root_url: str) -> str:
    """Extract host label from URL, supporting any domain suffix/TLD."""
    host_label = (urlparse(root_url).hostname or "unknown-host").lower()

    sanitized = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in host_label).strip("._-")
    return sanitized or "unknown-host"


async def run_crawl_test(
    tool_context: ToolContext,
    url: str,
    max_depth: int = 0,
    max_pages: int = 10,
    same_host_only: bool = True,
    session_id: str | None = None,
) -> dict[str, object]:
    """Run accessibility tests from root URL using BFS up to `max_depth`."""
    if max_depth < 0:
        return {"status": "error", "message": "max_depth must be >= 0."}
    if max_pages <= 0:
        return {"status": "error", "message": "max_pages must be > 0."}

    logger.info(f"Running crawler on {url} with {max_depth=}, {max_pages=}")

    try:
        root_url = normalize_url(url)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}

    root_host_label = _extract_root_host_label(root_url)
    crawl_folder_name = f"{generate_run_timestamp()}_{root_host_label}"
    tool_context.state[ContextKey.CRAWL_FOLDER_NAME] = crawl_folder_name

    logger.info(f"Crawl folder name: {tool_context.state[ContextKey.CRAWL_FOLDER_NAME]}")

    if not BROWSER_SESSION.is_initialized():
        await BROWSER_SESSION.create_session(session_id=session_id)

    crawl_session_service = InMemorySessionService()
    crawl_runner = Runner(
        app_name="ax_tester_crawl_internal",
        agent=tester_agent,
        session_service=crawl_session_service,
    )

    scheduled_urls: set[str] = {root_url}
    visited: set[str] = set()
    queue: deque[tuple[str, int]] = deque([(root_url, max_depth)])
    results: list[dict[str, object]] = []

    while queue and len(visited) < max_pages:
        current_url, depth = queue.popleft()
        if current_url in visited:
            continue

        visited.add(current_url)

        node_result: dict[str, object] = {
            "url": current_url,
            "depth_remaining": depth,
            "status": "pending",
            "error": "",
            "discovered_links": 0,
            "child_links": [],
        }
        results.append(node_result)

        await BROWSER_SESSION.goto(current_url)

        # extract child links before the test mutates page state
        child_links = []
        if depth > 0:
            try:
                child_links = await collect_links_from_current_page(
                    root_url=root_url,
                    same_host_only=same_host_only,
                )
            except Exception as exc:
                node_result["error"] = (
                    f"{node_result['error']} | link_extraction_error: {exc}"
                    if node_result["error"]
                    else f"link_extraction_error: {exc}"
                )

            node_result["discovered_links"] = len(child_links)
            node_result["child_links"] = child_links

            # enqueue new child links up to the max_pages cap
            for child_url in child_links:
                try:
                    child_url_normalized = normalize_url(child_url)
                except ValueError:
                    continue

                if child_url_normalized in scheduled_urls:
                    continue
                if len(scheduled_urls) >= max_pages:
                    break

                scheduled_urls.add(child_url_normalized)
                queue.append((child_url_normalized, depth - 1))

        # run the ax tester on the current page
        try:
            test_result = await _run_tester_once(
                runner=crawl_runner,
                session_service=crawl_session_service,
                page_url=current_url,
                crawl_folder_name=crawl_folder_name,
            )

            node_result["status"] = test_result.get("status", "unknown")
            node_result["final_response"] = test_result.get("final_response", "")
            node_result["current_url"] = await BROWSER_SESSION.get_current_url()
        except Exception as exc:
            node_result["status"] = "error"
            node_result["error"] = f"test_execution_error: {exc}"
            continue

    results_file, saved_reports, report_artifact = write_run_results_index(crawl_folder_name)
    tool_context.state[ContextKey.REPORT_ARTIFACT] = report_artifact

    await BROWSER_SESSION.close_session()

    return {
        "status": "ok",
        "run_timestamp": crawl_folder_name,
        "report_id": crawl_folder_name,
        "root_url": root_url,
        "max_depth": max_depth,
        "max_pages": max_pages,
        "same_host_only": same_host_only,
        "number_visited_pages": len(visited),
        "stopped_by_max_pages": len(visited) >= max_pages,
        "saved_page_reports": len(saved_reports),
        "results_file": str(results_file),
        **report_artifact,
        "visited_pages": list(visited),
    }


tester_agent = SequentialAgent(
    name="AccessibilityTesterAgent",
    description="Performs static, semantic and dynamic analysis on the current open page",
    sub_agents=[
        static_analysis_agent,
        image_analyzer_agent,
        navigator_agent,
        LlmAgent(
            name="Saver",
            model=DUMMY_MODEL,
            description="Save results in local repository",
            instruction="Use tool `run_save` once.",
            tools=[run_save],
        ),
    ],
)

root_agent = LlmAgent(
    name="RootAgent",
    model=MODEL,
    description="",
    instruction=ROOT_AGENT_INSTRUCTION,
    tools=[run_crawl_test],
)
