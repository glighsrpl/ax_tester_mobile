import base64
import json
import logging
import mimetypes
from typing import Any
from urllib.request import Request, urlopen

from common import MODEL_NAME
from tools.base import Tool, ToolExecutionError, ToolResult, ToolStatus
from utils.llm_helper import call_llm

logger = logging.getLogger(__name__)


DEFAULT_PROMPT = """
    You are an accessibility image captioner.
    Write short, descriptive captions suitable as alt text, and classify decorative images per WCAG 1.1.1.
    Be specific, avoid filler, and do not mention 'image' or 'photo'.
    If text is visible, include it verbatim.
    Return JSON ONLY as an array of objects with keys: index, caption, is_pure_decorative.
    Set is_pure_decorative to true only when the image is purely decorative:
    - no essential information
    - no functionality/action
    - no meaningful text that users need
    - only visual styling, spacing, or redundant ornament
    Set is_pure_decorative to false for informative, functional, or text-bearing images.
    If is_pure_decorative is true, return caption as an empty string.
    Do not add extra keys or commentary.
    Use valid JSON with double quotes.
    The index must match the number shown in the input label "Image {index}".

    Example output:
    [
        {"index": 0, "caption": "Red bicycle leaning against a brick wall", "is_pure_decorative": false},
        {"index": 1, "caption": "", "is_pure_decorative": true}
    ]
"""


class ImageCaptioner(Tool):
    """Generate image captions using an LLM. Downloads images and sends them to the model."""

    def __init__(self, config: dict[str, Any] | None = None):
        super().__init__(config)
        self.model = self.config.get("model", MODEL_NAME)
        self.temperature = self.config.get("temperature", 0.3)
        self.max_images_per_batch = self.config.get("max_images_per_batch", 5)
        self.max_prompt_chars = self.config.get("max_prompt_chars", 100_000)
        self.download_timeout = self.config.get("download_timeout", 15)
        self.max_image_bytes = self.config.get("max_image_bytes", 5_000_000)

    def execute(self, images_input: list[dict], **kwargs) -> ToolResult:
        logger.info(f"Generating captions for {len(images_input)} images with model={self.model}")

        try:
            page_url = kwargs.get("page_url", "")

            if images_input is None:
                raise ToolExecutionError("missing_images_input")

            max_images_per_batch = kwargs.get("max_images_per_batch", self.max_images_per_batch)
            max_prompt_chars = kwargs.get("max_prompt_chars", self.max_prompt_chars)

            prepared, skipped = self._prepare_images(images_input)
            batches = self._batch_images(prepared, max_images_per_batch, max_prompt_chars)

            captions: list[dict[str, Any]] = []
            for batch in batches:
                captions.extend(self._caption_batch(batch))

            merged = self._merge_with_images(images_input, captions)

            return ToolResult(
                tool_name="image-captioner",
                status=ToolStatus.SUCCESS,
                data={
                    "page": page_url,
                    "images": merged,
                    "skipped": len(skipped),
                },
                metadata={"url": page_url},
            )

        except ToolExecutionError:
            raise
        except Exception as e:
            logger.exception("Unexpected error in image captioner")
            return ToolResult(
                tool_name="image-captioner",
                status=ToolStatus.FAILURE,
                data={},
                error=str(e),
                metadata={"url": page_url},
            )

    def _prepare_images(self, images: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        prepared = []
        skipped = []
        for i, img in enumerate(images):
            url = img.get("url")
            if not url:
                skipped.append({"url": url, "reason": "missing_url"})
                continue
            try:
                data, mime = self._download_image(url)
                b64 = base64.b64encode(data).decode("ascii")
                prepared.append(
                    {
                        "index": i,
                        "url": url,
                        "alt_text": img.get("alt_text"),
                        "source_selector": img.get("source_selector"),
                        "outer_html": img.get("outer_html"),
                        "mime": mime,
                        "b64": b64,
                    }
                )
            except Exception as e:
                skipped.append({"url": url, "reason": str(e)})
        return prepared, skipped

    def _download_image(self, url: str) -> tuple[bytes, str]:
        req = Request(url, headers={"User-Agent": "ax-tester/1.0"})
        with urlopen(req, timeout=self.download_timeout) as resp:
            content_type = resp.headers.get("Content-Type", "")
            data = resp.read(self.max_image_bytes + 1)

        if len(data) > self.max_image_bytes:
            raise ToolExecutionError(f"image_too_large>{self.max_image_bytes}")

        mime = self._resolve_mime(url, content_type)
        if mime == "image/svg+xml" or url.lower().endswith(".svg"):
            data = self._convert_svg_to_png(data, url)
            mime = "image/png"
        return data, mime

    def _resolve_mime(self, url: str, content_type: str) -> str:
        if content_type and "/" in content_type:
            return content_type.split(";")[0].strip()
        guessed, _ = mimetypes.guess_type(url)
        return guessed or "application/octet-stream"

    def _convert_svg_to_png(self, data: bytes, url: str) -> bytes:
        try:
            import cairosvg

            return cairosvg.svg2png(bytestring=data)
        except (ImportError, OSError) as e:
            logger.warning(
                f"Skipping SVG image because CairoSVG or its native dependencies are unavailable: {url} ({e})"
            )
            raise ToolExecutionError("svg_to_png_unavailable") from e
        except Exception as e:
            logger.warning(f"Skipping SVG image because SVG conversion failed: {url} ({e})")
            raise ToolExecutionError(f"svg_to_png_failed:{e}") from e

    def _batch_images(
        self,
        images: list[dict[str, Any]],
        max_images_per_batch: int,
        max_prompt_chars: int,
    ) -> list[list[dict[str, Any]]]:
        batches: list[list[dict[str, Any]]] = []
        current: list[dict[str, Any]] = []
        base_prompt_len = len(DEFAULT_PROMPT)
        current_len = base_prompt_len

        for img in images:
            img_len = self._estimate_image_prompt_len(img)

            if current and (len(current) == max_images_per_batch or current_len + img_len > max_prompt_chars):
                batches.append(current)
                current = []
                current_len = base_prompt_len

            current.append(img)
            current_len += img_len

        if current:
            batches.append(current)

        return batches

    def _estimate_image_prompt_len(self, img: dict[str, Any]) -> int:
        alt = img.get("alt_text") or ""
        return len(img.get("b64", "")) + len(alt) + 200

    def _caption_batch(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        messages = self._build_messages(batch)
        response_text = call_llm(self.model, self.temperature, messages)
        return self._parse_captions(response_text, batch)

    def _build_messages(self, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []
        content.append(
            {
                "type": "text",
                "text": DEFAULT_PROMPT.strip(),
            }
        )

        for img in batch:
            label = f"Image {img['index']} | url: {img['url']}"
            content.append({"type": "text", "text": label})
            content.append(
                {
                    "type": "image_url",
                    "image_url": {"url": f"data:{img['mime']};base64,{img['b64']}"},
                }
            )

        return [{"role": "user", "content": content}]

    def _parse_captions(self, text: str, batch: list[dict[str, Any]]) -> list[dict[str, Any]]:
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None

        if isinstance(parsed, list):
            normalized: list[dict[str, Any]] = []
            for item in parsed:
                if not isinstance(item, dict):
                    continue
                if "index" not in item or "caption" not in item:
                    continue

                normalized.append(
                    {
                        "index": item.get("index"),
                        "caption": item.get("caption"),
                        "is_pure_decorative": self._to_bool(item.get("is_pure_decorative"), default=False),
                    }
                )
            if normalized:
                return normalized

        logger.warning("Failed to parse JSON from model response, returning fallback captions.")
        return [
            {
                "index": img["index"],
                "caption": img.get("alt_text") or "",
                "is_pure_decorative": False,
            }
            for img in batch
        ]

    def _to_bool(self, value: Any, default: bool = False) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"true", "1", "yes"}:
                return True
            if normalized in {"false", "0", "no"}:
                return False
        return default

    def _merge_with_images(
        self, images: list[dict[str, Any]], captions: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        merged = []
        for caption_obj in captions:
            idx = caption_obj.get("index")
            if not isinstance(idx, int) or idx < 0 or idx >= len(images):
                continue
            img = images[idx]
            merged.append(
                {
                    "index": idx,
                    "type": img.get("type"),
                    "url": img.get("url"),
                    "alt_text": img.get("alt_text"),
                    "caption": caption_obj.get("caption"),
                    "is_pure_decorative": bool(caption_obj.get("is_pure_decorative", False)),
                    "source_selector": img.get("source_selector"),
                    "outer_html": img.get("outer_html"),
                }
            )
        return merged


# sample usage for testing/debugging
if __name__ == "__main__":
    import asyncio
    import sys

    # single test
    page_url = "https://shop.reply.com"
    images = [
        {
            "type": "img",
            "url": "https://cdn.cookielaw.org/logos/static/powered_by_logo.svg",
            "alt_text": "Powered by Onetrust",
            "source_selector": "img",
        }
    ]

    result = ImageCaptioner().execute(images, page_url=page_url).data
    print(f"\n{result}")
    print(json.dumps(result["images"], indent=2))
    print("\n\n")

    # integration test with image extractor

    # default_url = "https://apple.com"
    default_url = "https://shop.reply.com"
    test_url = "https://shop.reply.com" if len(sys.argv) < 2 else sys.argv[1]

    from tools.image_extractor import ImageExtractor
    from utils.browser_session import BROWSER_SESSION

    async def _run() -> None:
        url = test_url if test_url.startswith(("http://", "https://")) else f"https://{test_url}"
        await BROWSER_SESSION.create_session()
        await BROWSER_SESSION.goto(url)
        try:
            extracted = (await ImageExtractor().execute()).data
        finally:
            await BROWSER_SESSION.close_session()

        print(f"Extracted {len(extracted['images'])} images")
        result = ImageCaptioner().execute(extracted["images"], page_url=extracted.get("page_url", ""))
        print(json.dumps(result.data, indent=2))

    asyncio.run(_run())
