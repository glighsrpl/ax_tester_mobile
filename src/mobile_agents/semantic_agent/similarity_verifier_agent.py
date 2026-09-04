"""Verify mobile image descriptions against vision-generated captions."""

from google.adk.agents.llm_agent import LlmAgent

from common import MODEL
from schemas import Report
from schemas.issues import WCAG_LEVEL_WEIGHTS
from utils.wcag_helper import get_rule_name_from_axe_tags

WCAG_RULE = get_rule_name_from_axe_tags(["wcag111"])
LEVEL_A_WEIGHT = WCAG_LEVEL_WEIGHTS["A"]

SIMILARITY_VERIFIER_PROMPT = f"""
    You receive `images_inventory`, `captions`, `page`, and `screenshot_path`.
    `images_inventory` is a list of dictionaries with index, resource_id,
    content_description, class_name, and bounds. `captions` is a list of
    dictionaries with index and caption.

    For each image, match its inventory item to its caption by index. Evaluate
    whether content_description semantically matches the caption. Be lenient
    with language differences: an Italian content_description and an English
    caption are a match when they describe the same thing.

    An empty content_description is a missing-description failure. A non-empty
    content_description that does not semantically match its caption is a
    mismatch failure. A semantic match passes and produces no issue.

    Return ONLY a complete, valid Report with no Markdown, explanations, or
    additional fields:
    - tool_name: "semantic_image_analyzer"
    - total_issues: the number of failures.
    - page: the received page.
    - issue_list: one Issue for each failing image, in inventory order.
    - score_total: level_A is total images multiplied by {LEVEL_A_WEIGHT};
      level_AA and level_AAA are zero.
    - score_passed: level_A is passed images multiplied by {LEVEL_A_WEIGHT};
      level_AA and level_AAA are zero.
    - metadata: an empty list.

    For every failing image, set:
    - id: "mobile-semantic-{{index}}-{{resource_id}}"
    - wcag_rule: "{WCAG_RULE}"
    - source: "llm/semantic_analyzer"
    - html_snippet: "resource_id={{resource_id}} class={{class_name}} bounds={{bounds}}"
    - why_this_matters: "Users relying on screen readers need accurate descriptions to understand image content"
    - potential_exposures: [{{"category": "Non-text content", "description": "Screen reader users cannot perceive the information conveyed by this image"}}]
    - image_url_or_path: screenshot_path when it is available; otherwise null.

    For a missing-description failure, set:
    - description: "Image has no content_description"
    - severity: "critical"
    - confidence: "high"
    - fix: "Add a meaningful content_description to this image"

    For a mismatch failure, set:
    - description: "Image content_description '{{content_description}}' does not match visual content: '{{caption}}'"
    - severity: "moderate"
    - confidence: "medium" when the mismatch is uncertain or low-confidence;
      otherwise "high" when the description is clearly wrong.
    - fix: "Update content_description to accurately describe the image content"
"""

similarity_verifier = LlmAgent(
    name="similarity_verifier",
    model=MODEL,
    description="Return a WCAG report for missing or inaccurate mobile image descriptions.",
    instruction=SIMILARITY_VERIFIER_PROMPT,
    output_schema=Report,
)
