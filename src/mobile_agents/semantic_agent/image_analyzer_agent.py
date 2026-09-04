"""Orchestrate semantic image accessibility analysis for mobile screens."""

from google.adk.agents.llm_agent import LlmAgent
from google.adk.tools import AgentTool, FunctionTool

from common import MODEL, MobileContextKey
from mobile_agents.semantic_agent.caption_generator_agent import caption_generator
from mobile_agents.semantic_agent.tools.crop_images import crop_images
from mobile_agents.semantic_agent.tools.extract_images import extract_images
from mobile_agents.semantic_agent.tools.verify_similarity import verify_similarity
from schemas import Report
from schemas.issues import WCAG_LEVEL_WEIGHTS
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag111"])

SEMANTIC_IMAGE_ANALYZER_PROMPT = f"""
    Analyze the current mobile screen for WCAG 1.1.1 non-text-content issues.
    The input context provides the screen's screenshot, XML tree, and page.

    Execute these tools strictly in this order, passing each result to the next
    applicable step:

    1. Call `extract_images` with the XML tree to obtain `images_inventory`.
    2. Call `crop_images` with the screenshot and `images_inventory` to obtain
       `cropped_images`.
    3. Call `caption_generator` with `cropped_images` to obtain `captions`.
    4. Call `verify_similarity` with `images_inventory` and `captions` to obtain
       the semantic verification result.

    Build and return ONLY a valid Report from the verification result. Do not
    return tool inputs, intermediate data, Markdown, or explanations.

    Report requirements:
    - tool_name is "semantic_image_analyzer".
    - total_issues is the number of verification items whose status is
      "missing" or "mismatch".
    - page is the page received in the input context.
    - metadata is an empty list.
    - Include one Issue for every item with status "missing" or "mismatch", in
      verification-result order. Give it the id
      "mobile-semantic-{{index}}-{{resource_id}}".
    - Each Issue's wcag_rule is "{WCAG_RULE}" and source is
      "semantic_analyzer".
    - For missing: description is "Image has no content_description",
      severity is "critical", and fix is "Add a meaningful
      content_description to this image".
    - For mismatch: description is "Image content_description
      '{{content_description}}' does not match visual content: '{{caption}}'",
      severity is "moderate", and fix is "Update content_description to
      accurately describe the image content".
    - confidence uses similarity_score when it is available: below 0.5 is
      "high"; from 0.5 through 0.75 is "medium". Missing descriptions have no
      similarity_score and use "high" confidence.
    - html_snippet contains the image XML node attributes resource_id,
      class_name, and bounds from its matching images_inventory entry.
    - why_this_matters is "Users relying on screen readers need accurate
      descriptions to understand image content".
    - potential_exposures is [{{"category": "Non-text content",
      "description": "Screen reader users cannot perceive the information
      conveyed by this image"}}].
    - image_url_or_path is the screenshot path when it is available; otherwise
      null.
    - WCAG 1.1.1 is Level A. Set score_total.level_A to the total number of
      images multiplied by WCAG_LEVEL_WEIGHTS["A"] ({WCAG_LEVEL_WEIGHTS["A"]}),
      and score_passed.level_A to the passed-image count multiplied by that
      weight. Set all other score levels to zero.
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
        FunctionTool(func=verify_similarity),
    ],
    output_schema=Report,
    output_key=MobileContextKey.SEMANTIC_RESULTS,
)
