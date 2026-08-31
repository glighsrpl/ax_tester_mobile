import json
import logging

from google.adk.agents import SequentialAgent
from google.adk.agents.llm_agent import LlmAgent
from google.adk.agents.parallel_agent import ParallelAgent
from google.adk.tools.tool_context import ToolContext

from agents.static_agent.axe_core_agent import axe_agent
from agents.static_agent.axe_enrichment_agent import axe_enrichment_agent
from agents.static_agent.init_agent import init_agent
from agents.static_agent.llm_finder_agent import loop_agent
from common import MODEL, ContextKey
from schemas import Report

logger = logging.getLogger(__name__)


def get_merge_agent_instruction(tool_context: ToolContext) -> str:
    loop_report = tool_context.state.get(ContextKey.LOOP_REPORT, {"issue_list": []})
    if isinstance(loop_report, str):
        try:
            loop_report = json.loads(loop_report)
        except Exception:
            loop_report = {"issue_list": []}

    axe_report = tool_context.state.get(ContextKey.AXE_REPORT, {})
    axe_issue_list = []
    page_url = ""
    if isinstance(axe_report, dict):
        axe_issue_list = axe_report.get("data", {}).get("issue_list", [])
        page_url = axe_report.get("data", {}).get("url", "")

    axe_report_json = json.dumps(axe_issue_list, ensure_ascii=True)
    loop_report_json = json.dumps(loop_report, ensure_ascii=True)
    loop_issue_count = len(loop_report.get("issue_list", [])) if isinstance(loop_report, dict) else 0
    logger.info(
        f"Preparing MergeReportsAgent prompt: "
        f"axe_issues={len(axe_issue_list)}, loop_issues={loop_issue_count}, page={page_url}"
    )

    return (
        f"""
        You are a REPORT MERGER tasked with combining two accessibility issue reports into one comprehensive report.
        Merge axe_report_issue_list and loop_report into a comprehensive unified report.
        Note that axe_report_issue_list is pre-normalized into issue_list schema.
        Make sure to include all issue from axe_report_issue_list and loop_report, but de-duplicate same issue.

        axe_report_issue_list:
        {axe_report_json}

        loop_report:
        {loop_report_json}

        page:
        {page_url}
        """
        + """

        Merging rules:
        1. De-duplicate by WCAG rule + similar description
        2. If same issue found by both: mark as 'confidence: high'
        3. Preserve all unique issues from both sources
        4. Add 'source' field: 'axe-core' | 'llm' | 'both'

        OUTPUT SCHEMA:
        - tool_name: "static-analysis"
        - issue_list: final deduplicated issue list
          Each issue must include:
          id, wcag_rule, description, severity, source, confidence, html_snippet, fix, image_url_or_path
          why_this_matters, potential_exposures
          (set image_url_or_path to null when unknown)
          - why_this_matters: one concise, plain-language sentence about the user impact
          - potential_exposures: list of objects with category and description strings
            Keep category short and keep description to one concise sentence.
        - total_issues: number of unique issues
        - page: analyzed page URL
        - score_passed: object {level_A, level_AA, level_AAA}
        - score_total: object {level_A, level_AA, level_AAA}
          If exact static scoring is not available, set both objects to zeros.
        - metadata: list of objects with fields {key, value}
          Required metadata keys:
          - by_severity (JSON string)
          - by_source (JSON string)
          - by_wcag_level (JSON string)
          - coverage_score (integer)

        Return ONLY the JSON object, no other text.
        Keep html_snippet concise and valid JSON strings.
    """
    )


axe_enriched_agent = SequentialAgent(
    name="AxeCoreWithEnrichmentAgent",
    sub_agents=[axe_agent, axe_enrichment_agent],
    description="Run axe-core and enrich its issues with qualitative fields.",
)

axe_llm_agent = ParallelAgent(
    name="AxeAndLLMAgent",
    sub_agents=[axe_enriched_agent, loop_agent],
    description=(
        "Run enriched axe-core analysis and the LLM loop audit. Wait for both to complete, then return a brief confirmation."
    ),
)

merge_agent = LlmAgent(
    name="MergeReportsAgent",
    model=MODEL,
    instruction=get_merge_agent_instruction,
    output_schema=Report,
    description="Merge axe-core and LLM loop reports into a unified accessibility report.",
    output_key=ContextKey.STATIC_REPORT,
)

static_analysis_agent = SequentialAgent(
    name="StaticAccessibilityAgent",
    description="Run axe-core and LLM loop audit to generate comprehensive accessibility report.",
    sub_agents=[init_agent, axe_llm_agent, merge_agent],
)
