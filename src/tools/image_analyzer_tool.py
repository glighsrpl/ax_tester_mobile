import json
import logging
import re
from typing import Any

from schemas import Issue, ScoreInfo
from tools.base import Tool, ToolExecutionError, ToolResult, ToolStatus
from tools.image_captioner import ImageCaptioner
from tools.image_extractor import ImageExtractor
from utils.llm_helper import call_llm
from utils.wcag_helper import get_rule_name_from_axe_tags

logger = logging.getLogger(__name__)

WCAG_RULE = get_rule_name_from_axe_tags(["wcag111"])

SIMILARITY_PROMPT = """
    You compare alt text and generated captions for the same image.
    Return JSON ONLY as an array of objects with keys: index, similar.
    similar must be true if the alt text and caption convey the same essential information.
    Don't be too strict: minor wording differences are OK, missing key information is NOT OK.
    If the alt text is empty, return false. If the caption is empty, return false.
    The index must match the number shown in the input label "Image {index}".
    Do not add extra keys or commentary. Use valid JSON with double quotes.

    Example output:
    [
        {"index": 0, "similar": true},
        {"index": 1, "similar": false}
    ]
"""


class ImageAnalyzerTool(Tool):
    """Orchestrates image extraction and captioning.
    Runs ImageExtractor first, then ImageCaptioner on the extracted images,
    then compares alt text vs caption with an LLM.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        extractor_config = self.config.get("extractor", {})
        captioner_config = self.config.get("captioner", {})
        self.temperature = self.config.get("temperature", 0.0)
        self.max_items_per_batch = self.config.get("max_items_per_batch", 20)
        self.extractor = ImageExtractor(extractor_config)
        self.captioner = ImageCaptioner(captioner_config)
        self.model = self.captioner.model

    async def execute(self, **kwargs) -> ToolResult:
        logger.info("Analyzing images on current page")

        page_url = ""
        try:
            extractor_kwargs = kwargs.get("extractor_kwargs", {})
            captioner_kwargs = kwargs.get("captioner_kwargs", {})

            # extract images from the current page
            extracted: ToolResult = await self.extractor.execute(**extractor_kwargs)
            page_url = extracted.data.get("page_url", "")
            if not extracted.is_success():
                return ToolResult(
                    tool_name="image-analyzer",
                    status=ToolStatus.FAILURE,
                    data={},
                    score_passed=ScoreInfo(),
                    score_total=ScoreInfo(),
                    error=extracted.error or "image_extractor_failed",
                    metadata=extracted.metadata or {"url": page_url},
                )

            images = extracted.data.get("images", [])

            # generate caption for extracted images
            captions_result = self.captioner.execute(images, page_url=page_url, **captioner_kwargs)
            if not captions_result.is_success():
                return ToolResult(
                    tool_name="image-analyzer",
                    status=ToolStatus.FAILURE,
                    data={},
                    score_passed=ScoreInfo(),
                    score_total=ScoreInfo(),
                    error=captions_result.error or "image_captioner_failed",
                    metadata=captions_result.metadata or {"url": page_url},
                )

            all_captioned_images = captions_result.data.get("images", [])

            # remove pure decorative images
            captioned_images = [img for img in all_captioned_images if not img.get("is_pure_decorative")]
            for idx, img in enumerate(captioned_images):
                img["index"] = idx
            tot_pure_decorative = len(all_captioned_images) - len(captioned_images)

            # analyze image similarity
            logger.info(f"Analyzing similarity of alt text and captions for {len(captioned_images)} images")
            similarity = self._analyze_similarity(captioned_images)

            issue_list: list[dict[str, Any]] = []
            for idx, sim in enumerate(similarity):
                img = captioned_images[idx]
                if not sim:
                    issue = Issue(
                        id=f"image-alt-mismatch-{idx}",
                        wcag_rule=WCAG_RULE,
                        description="Missing alt text" if not img.get("alt_text") else "Inconsistent alt text",
                        html_snippet=img.get("outer_html") or img.get("source_selector") or "",
                        severity="critical",
                        confidence="high",
                        source="llm/image-analyzer",
                        fix=f"Improve alt text, e.g. {img.get('caption')}",
                        image_url_or_path=img.get("url"),
                        why_this_matters=(
                            "Screen reader users may miss the purpose of this image or receive misleading information."
                        ),
                        potential_exposures=[
                            {
                                "category": "User impact",
                                "description": "Non-visual users may not get the same information as sighted users.",
                            },
                            {
                                "category": "Content accuracy",
                                "description": "The page may communicate incomplete or incorrect meaning through assistive technology.",
                            },
                        ],
                    ).model_dump()
                    issue_list.append(issue)

            return ToolResult(
                tool_name="image-analyzer",
                status=ToolStatus.SUCCESS,
                data={
                    "page": captions_result.data.get("page", page_url),
                    "issue_list": issue_list,
                    "skipped": captions_result.data.get("skipped", 0),
                    "extracted": len(images),
                    "decorative": tot_pure_decorative,
                },
                score_passed=ScoreInfo(level_A=len(captioned_images) - len(issue_list)),
                score_total=ScoreInfo(level_A=len(captioned_images)),
                metadata={"url": page_url},
            )

        except ToolExecutionError:
            raise
        except Exception as e:
            logger.exception("Unexpected error in image analyzer tool")
            return ToolResult(
                tool_name="image-analyzer",
                status=ToolStatus.FAILURE,
                data={},
                score_passed=ScoreInfo(),
                score_total=ScoreInfo(),
                error=str(e),
                metadata={"url": page_url},
            )

    def _analyze_similarity(self, images: list[dict[str, Any]]) -> list[bool]:
        items = []
        for i, img in enumerate(images):
            idx = img.get("index", i)
            items.append(
                {
                    "index": idx,
                    "alt_text": img.get("alt_text") or "",
                    "caption": img.get("caption") or "",
                }
            )

        # extract batch analysis
        batches = self._batch_items(items, self.max_items_per_batch)
        results: list[dict[str, Any]] = []
        for batch in batches:
            results.extend(self._analyze_batch(batch))

        by_index = {r.get("index"): r.get("similar") for r in results if isinstance(r, dict)}
        out: list[bool] = []
        for item in items:
            val = by_index.get(item.get("index"))
            out.append(bool(val) if val is not None else False)
        return out

    def _batch_items(self, items: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
        if size <= 0:
            return [items]
        return [items[i : i + size] for i in range(0, len(items), size)]

    def _analyze_batch(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages = self._build_similarity_messages(batch)
        response_text = call_llm(self.model, self.temperature, messages)
        return self._parse_similarity(response_text)

    def _build_similarity_messages(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": SIMILARITY_PROMPT.strip()}]
        for item in batch:
            idx = item.get("index")
            alt_text = item.get("alt_text") or ""
            caption = item.get("caption") or ""
            content.append(
                {
                    "type": "text",
                    "text": f"Image {idx}\nAlt text: {alt_text}\nCaption: {caption}",
                }
            )
        return [{"role": "user", "content": content}]

    def _parse_similarity(self, text: str) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(text)
        except Exception:
            match = re.search(r"(\[.*\])", text, re.DOTALL)
            if not match:
                return []
            try:
                parsed = json.loads(match.group(1))
            except Exception:
                return []
        if isinstance(parsed, list):
            normalized: list[dict[str, Any]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                if "index" not in item or "similar" not in item:
                    continue
                normalized.append(
                    {
                        "index": item.get("index"),
                        "similar": bool(item.get("similar")),
                    }
                )
            if normalized:
                return normalized
        return []


# integration test
if __name__ == "__main__":
    import asyncio
    import sys

    from utils.browser_session import BROWSER_SESSION

    # default_url = "https://apple.com"
    default_url = "https://shop.reply.com"
    test_url = default_url if len(sys.argv) < 2 else sys.argv[1]

    async def _run() -> None:
        url = test_url if test_url.startswith(("http://", "https://")) else f"https://{test_url}"
        await BROWSER_SESSION.create_session()
        await BROWSER_SESSION.goto(url)
        try:
            result = await ImageAnalyzerTool().execute()
            print(json.dumps(result.data, indent=2))
        finally:
            await BROWSER_SESSION.close_session()

    asyncio.run(_run())
