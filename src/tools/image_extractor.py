import asyncio
import logging
import re

from tools.base import Tool, ToolExecutionError, ToolResult, ToolStatus
from utils.browser_session import BROWSER_SESSION

logger = logging.getLogger(__name__)

URL_RE = re.compile(r"url\([\'\"](.*?)[\'\"]\)")

JS_COLLECT = r"""
() => {
  function getAltAttributeFlags(el) {
    if (!el || typeof el.hasAttribute !== 'function') {
      return {
        has_alt_attribute: false,
        is_empty_alt: false
      };
    }
    const hasAlt = el.hasAttribute('alt');
    const alt = hasAlt ? (el.getAttribute('alt') || '') : '';
    return {
      has_alt_attribute: hasAlt,
      is_empty_alt: hasAlt && alt.trim() === ''
    };
  }

  function getAltLike(el) {
    // priority: alt (img) -> aria-label -> aria-labelledby -> figcaption/closest figure -> title

    // alt
    if (el.tagName === 'IMG') {
      const alt = el.getAttribute('alt');
      if (alt !== null) return alt; // can be empty
    }

    // aria-label
    const ariaLabel = el.getAttribute('aria-label');
    if (ariaLabel) return ariaLabel;

    // aria-labelledby
    const labelledBy = el.getAttribute('aria-labelledby');
    if (labelledBy) {
      const ids = labelledBy.split(/\s+/).filter(Boolean);
      const text = ids
        .map(id => document.getElementById(id))
        .filter(Boolean)
        .map(n => (n.innerText || n.textContent || '').trim())
        .filter(Boolean)
        .join(' ');
      if (text) return text;
    }

    // figcaption
    const figure = el.closest('figure');
    if (figure) {
      const fc = figure.querySelector('figcaption');
      if (fc) {
        const t = (fc.innerText || fc.textContent || '').trim();
        if (t) return t;
      }
    }

    // title
    const title = el.getAttribute('title');
    if (title) return title;

    return null;
  }

  function selectorFor(el) {
    // light selector for debugging
    if (!el) return null;
    const id = el.getAttribute && el.getAttribute('id');
    if (id) return `#${CSS.escape(id)}`;
    const cls = el.getAttribute && el.getAttribute('class');
    if (cls) {
      const c = cls.split(/\s+/).filter(Boolean)[0];
      if (c) return `${el.tagName.toLowerCase()}.${CSS.escape(c)}`;
    }
    return el.tagName ? el.tagName.toLowerCase() : null;
  }

  function outerHtmlFor(el) {
    return (el && typeof el.outerHTML === 'string') ? el.outerHTML : null;
  }

  const results = [];

  // 1) <img>
  document.querySelectorAll('img').forEach(img => {
    results.push({
      type: 'img',
      url: img.currentSrc || img.src || null,
      alt_text: getAltLike(img),
      source_selector: selectorFor(img),
      outer_html: outerHtmlFor(img),
      ...getAltAttributeFlags(img)
    });
  });

  // 2) SVG <image href=...> (rare but possible)
  document.querySelectorAll('svg image').forEach(im => {
    const href = im.getAttribute('href') || im.getAttribute('xlink:href');
    results.push({
      type: 'svg-image',
      url: href,
      alt_text: getAltLike(im),
      source_selector: selectorFor(im),
      outer_html: outerHtmlFor(im),
      ...getAltAttributeFlags(im)
    });
  });

  // 3) Elements with CSS background-image (including role="img")
  const all = Array.from(document.querySelectorAll('body *'));
  for (const el of all) {
    const cs = getComputedStyle(el);
    const bg = cs.backgroundImage;
    if (bg && bg !== 'none' && bg.includes('url(')) {
      results.push({
        type: 'css-background',
        url: bg, // keep raw; parse in python to extract url(...)
        alt_text: getAltLike(el),
        source_selector: selectorFor(el),
        outer_html: outerHtmlFor(el),
        ...getAltAttributeFlags(el)
      });
    }

    // pseudo-elements
    const b1 = getComputedStyle(el, '::before').backgroundImage;
    if (b1 && b1 !== 'none' && b1.includes('url(')) {
      results.push({
        type: 'css-background::before',
        url: b1,
        alt_text: getAltLike(el),
        source_selector: selectorFor(el),
        outer_html: outerHtmlFor(el),
        ...getAltAttributeFlags(el)
      });
    }
    const b2 = getComputedStyle(el, '::after').backgroundImage;
    if (b2 && b2 !== 'none' && b2.includes('url(')) {
      results.push({
        type: 'css-background::after',
        url: b2,
        alt_text: getAltLike(el),
        source_selector: selectorFor(el),
        outer_html: outerHtmlFor(el),
        ...getAltAttributeFlags(el)
      });
    }

    // content: url(...) on pseudo-elements
    const c1 = getComputedStyle(el, '::before').content;
    if (c1 && c1.startsWith('url(')) {
      results.push({
        type: 'css-content::before',
        url: c1,
        alt_text: getAltLike(el),
        source_selector: selectorFor(el),
        outer_html: outerHtmlFor(el),
        ...getAltAttributeFlags(el)
      });
    }
    const c2 = getComputedStyle(el, '::after').content;
    if (c2 && c2.startsWith('url(')) {
      results.push({
        type: 'css-content::after',
        url: c2,
        alt_text: getAltLike(el),
        source_selector: selectorFor(el),
        outer_html: outerHtmlFor(el),
        ...getAltAttributeFlags(el)
      });
    }
  }

  return results;
}
"""


class ImageExtractor(Tool):
    """Extract images and image-like resources from a webpage using Playwright."""

    async def execute(self, **kwargs) -> ToolResult:
        """Extract images from the current page in `BROWSER_SESSION`."""
        page_url = await BROWSER_SESSION.get_current_url() if BROWSER_SESSION.is_initialized() else ""
        logger.info(f"Extracting images from current page {page_url}")

        try:
            result = await self._extract_images_async()
            return ToolResult(
                tool_name="image-extractor",
                status=ToolStatus.SUCCESS,
                data=result,
                metadata={"url": result.get("page_url", page_url)},
            )
        except ToolExecutionError:
            raise
        except Exception as e:
            logger.exception(f"Unexpected error in image extractor for {page_url}")
            return ToolResult(
                tool_name="image-extractor",
                status=ToolStatus.FAILURE,
                data={},
                error=str(e),
                metadata={"url": page_url},
            )

    async def _extract_images_async(self) -> dict:
        if not BROWSER_SESSION.is_initialized():
            raise ToolExecutionError(
                "Browser session not initialized. Initialize and navigate with root tools before extracting images."
            )

        raw = await BROWSER_SESSION.evaluate(JS_COLLECT)
        if not isinstance(raw, list):
            raise ToolExecutionError("Image Extractor evaluate returned a non-list payload")

        out = []
        for item in raw:
            url_raw = item.get("url")
            if not url_raw:
                continue

            item_type = item.get("type") or ""
            if item_type.startswith("css-") and isinstance(url_raw, str):
                url = self._extract_url(url_raw)
            else:
                url = url_raw

            if not isinstance(url, str):
                continue
            if url in ("", "about:blank"):
                continue
            if not (url.startswith("https://") or url.startswith("http://")):
                continue

            out.append(
                {
                    "type": item_type,
                    "url": url,
                    "alt_text": item.get("alt_text", "") or "",
                    "source_selector": item.get("source_selector"),
                    "outer_html": item.get("outer_html"),
                    "has_alt_attribute": bool(item.get("has_alt_attribute")),
                    "is_empty_alt": bool(item.get("is_empty_alt")),
                }
            )

        # remove decorative image-like elements explicitly marked with empty `alt`
        out = [img for img in out if not (img.get("has_alt_attribute") and img.get("is_empty_alt"))]

        # deduplication
        dedup = {}
        for x in out:
            key = (x["url"], x.get("alt_text"), x.get("type"))
            dedup[key] = x

        return {
            "page_url": await BROWSER_SESSION.get_current_url(),
            "images": list(dedup.values()),
        }

    def _extract_url(self, css_value: str):
        if not css_value:
            return None
        m = URL_RE.search(css_value)
        return m.group(1) if m else None


# sample usage for testing/debugging
if __name__ == "__main__":
    import json
    import sys

    logging.basicConfig(level=logging.INFO)

    # default_url = "https://apple.com"
    default_url = "https://shop.reply.com"
    test_url = default_url if len(sys.argv) < 2 else sys.argv[1]

    async def _run() -> None:
        url = test_url if test_url.startswith(("http://", "https://")) else f"https://{test_url}"
        await BROWSER_SESSION.create_session()
        await BROWSER_SESSION.goto(url)
        try:
            result = (await ImageExtractor().execute()).data

            assert type(result) is dict, f"Expected dict, got {type(result)}"
            assert type(result["images"]) is list, f"Expected list, got {type(result['images'])}"
            if result["images"]:
                assert type(result["images"][0]) is dict, f"Expected dict, got {type(result['images'][0])}"
            print(json.dumps(result, indent=2, ensure_ascii=False))
        finally:
            await BROWSER_SESSION.close_session()

    asyncio.run(_run())
