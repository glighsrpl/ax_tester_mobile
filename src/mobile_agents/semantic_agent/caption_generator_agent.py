"""Vision sub-agent that captions cropped mobile UI elements."""

from google.adk.agents.llm_agent import LlmAgent

from common import MODEL

CAPTION_GENERATOR_PROMPT = """
    You receive cropped PNG images of mobile UI elements, each accompanied by
    its original inventory index. Inspect every image with vision and produce
    a short, one-sentence English caption describing what it depicts.

    Include visually meaningful details when available, such as the element
    type, icon, colour, subject, or chart content. Examples include "a red
    shopping cart icon", "a user profile photo", and "a bar chart showing
    monthly revenue". Do not infer functionality that is not visible.

    Return ONLY a valid JSON list, with one object per received image, in
    this exact shape:
    [{"index": 0, "caption": "..."}]

    Preserve every received index exactly so captions remain traceable to the
    image inventory. Do not include Markdown, explanations, or extra keys.
"""

caption_generator = LlmAgent(
    name="caption_generator",
    model=MODEL,
    description="Generate concise visual captions for cropped mobile UI elements.",
    instruction=CAPTION_GENERATOR_PROMPT,
)
