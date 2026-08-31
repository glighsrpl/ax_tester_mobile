"""Utilities for deterministic site crawling from the current browser page."""

from urllib.parse import urldefrag, urlparse, urlunparse

from utils.browser_session import BROWSER_SESSION

JS_COLLECT_PAGE_LINKS = """
() => {
  const out = [];
  const elements = document.querySelectorAll('a[href], area[href]');
  for (const el of elements) {
    const href = (el.href || '').trim();
    if (href) out.push(href);
  }
  return out;
}
"""

_NON_HTML_EXTENSIONS = {
    ".7z",
    ".avi",
    ".bmp",
    ".css",
    ".csv",
    ".doc",
    ".docx",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".m4a",
    ".m4v",
    ".mov",
    ".mp3",
    ".mp4",
    ".mpeg",
    ".mpg",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".svg",
    ".tar",
    ".tgz",
    ".txt",
    ".wav",
    ".webm",
    ".webp",
    ".woff",
    ".woff2",
    ".xls",
    ".xlsx",
    ".xml",
    ".zip",
}


def normalize_url(url: str) -> str:
    """Normalize URL for crawler deduplication and comparisons."""
    candidate = (url or "").strip()
    if not candidate:
        raise ValueError("URL cannot be empty.")

    if candidate.startswith("//"):
        candidate = f"https:{candidate}"

    parsed = urlparse(candidate)
    if not parsed.scheme:
        candidate = f"https://{candidate.lstrip('/')}"
        parsed = urlparse(candidate)

    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise ValueError(f"Unsupported URL scheme: {scheme or '<empty>'}")

    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError("URL must include a valid host.")

    port = parsed.port
    default_port = (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    netloc = host if port is None or default_port else f"{host}:{port}"

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    normalized = urlunparse((scheme, netloc, path, "", parsed.query, ""))
    normalized, _ = urldefrag(normalized)
    return normalized


def _is_same_host(url: str, root_url: str) -> bool:
    """Return True when two URLs have the same hostname."""
    return (urlparse(url).hostname or "").lower() == (urlparse(root_url).hostname or "").lower()


def is_probably_html_document(url: str) -> bool:
    """Heuristic to keep crawl focused on navigable HTML-like pages."""
    path = (urlparse(url).path or "").lower()
    if not path or path.endswith("/"):
        return True

    last_segment = path.rsplit("/", 1)[-1]
    if "." not in last_segment:
        return True

    ext = f".{last_segment.rsplit('.', 1)[-1]}"
    return ext not in _NON_HTML_EXTENSIONS


async def collect_links_from_current_page(root_url: str, same_host_only: bool = True) -> list[str]:
    """Collect normalized links from current page in BROWSER_SESSION."""
    if not BROWSER_SESSION.is_initialized():
        raise RuntimeError("Browser session not initialized.")

    raw_links = await BROWSER_SESSION.evaluate(JS_COLLECT_PAGE_LINKS)
    if not isinstance(raw_links, list):
        return []

    current_url = normalize_url(await BROWSER_SESSION.get_current_url())
    collected: list[str] = []
    seen: set[str] = set()

    for raw_link in raw_links:
        if not isinstance(raw_link, str):
            continue

        if raw_link.lower().startswith(("mailto:", "tel:", "javascript:")):
            continue

        try:
            link = normalize_url(raw_link)
        except ValueError:
            continue

        if (
            link == current_url
            or (same_host_only and not _is_same_host(link, root_url))
            or not is_probably_html_document(link)
            or link in seen
        ):
            continue

        seen.add(link)
        collected.append(link)

    return sorted(collected)
