"""Orchestrate semantic image accessibility analysis for mobile screens."""

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools import AgentTool, FunctionTool

from common import MODEL, MobileContextKey
from mobile_agents.semantic_agent.caption_generator_agent import caption_generator
from mobile_agents.semantic_agent.similarity_verifier_agent import similarity_verifier
from mobile_agents.semantic_agent.tools.crop_images import crop_images
from mobile_agents.semantic_agent.tools.extract_images import extract_images
from schemas import Report

SEMANTIC_IMAGE_ANALYZER_PROMPT = """
    Analyze the current mobile screen for WCAG 1.1.1 non-text-content issues.
    The input context provides the screen's screenshot, XML tree, and page.

    Execute these tools strictly in this order, passing each result to the next
    applicable step:

    1. Call `extract_images` with the XML tree to obtain `images_inventory`.
    2. Call `crop_images` with the screenshot and `images_inventory` to obtain
       `cropped_images`.
    3. Call `caption_generator` with `cropped_images` to obtain `captions`.
    4. Call `similarity_verifier` with `images_inventory`, `captions`, `page`,
       and `screenshot_path` to obtain the final Report.

    Return the Report from `similarity_verifier` as-is. Do not modify it or
    return tool inputs, intermediate data, Markdown, or explanations.
"""

image_analyzer_agent = LlmAgent(
    name="SemanticImageAnalyzerAgent",
    model=MODEL,
    description="Analyze mobile images for missing or inaccurate accessibility descriptions.",
    instruction=SEMANTIC_IMAGE_ANALYZER_PROMPT,
    tools=[
        FunctionTool(func=extract_images),
        FunctionTool(func=crop_images),
        AgentTool(agent=caption_generator),
        AgentTool(agent=similarity_verifier),
    ],
    output_schema=Report,
    output_key=MobileContextKey.SEMANTIC_RESULTS,
)
