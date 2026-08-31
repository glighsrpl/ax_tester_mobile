import logging
import os
from enum import StrEnum
from typing import Any

logger = logging.getLogger(__name__)

AXTESTER_EXECUTOR_ENV = "AXTESTER_EXECUTOR"
DEFAULT_AXTESTER_EXECUTOR = "mcp"
SUPPORTED_BROWSER_BACKENDS = {"local", "mcp"}


class NavigationCommand(StrEnum):
    """Command usable for navigation."""

    TAB = "Tab"
    SHIFT_TAB = "Shift+Tab"
    SPACE = "Space"
    ENTER = "Enter"
    ESCAPE = "Escape"


def get_browser_backend() -> str:
    """Return the configured browser backend: `mcp` or `local`."""
    value = os.getenv(AXTESTER_EXECUTOR_ENV, DEFAULT_AXTESTER_EXECUTOR)
    backend = value.strip().lower()
    if backend not in SUPPORTED_BROWSER_BACKENDS:
        supported = ", ".join(sorted(SUPPORTED_BROWSER_BACKENDS))
        raise ValueError(f"{AXTESTER_EXECUTOR_ENV} must be one of: {supported}")

    return backend


BROWSER_BACKEND = get_browser_backend()

if BROWSER_BACKEND == "local":
    from utils.browser_executor_client_local import BrowserSessionLocal as BrowserSession

else:
    from utils.browser_executor_client import BrowserExecutorClient

    class BrowserSession:
        """Facade over the external browser executor MCP server."""

        def __init__(self, client: BrowserExecutorClient | None = None) -> None:
            self.client = client or BrowserExecutorClient()
            self._initialized = False
            self._current_url = ""

        def is_initialized(self) -> bool:
            """Return True when an executor browser session has been created."""
            return self._initialized and bool(self.client.session_id)

        async def create_session(self, session_id: str | None = None) -> None:
            """Create a fresh browser session through the executor MCP server."""
            if self.is_initialized():
                await self.close_session()

            if session_id is not None:
                self.client.session_id = session_id
            else:
                await self.client.call_tool(
                    "create_session_web",
                    {"initial_url": "about:blank"},
                    include_session_id=False,
                )

            self._initialized = True

        async def press_key(
            self, key: NavigationCommand | str, tab_delay_ms: int = 50, expand_delay_ms: int = 1000
        ) -> None:
            """Press a keyboard key on the active executor page and wait for UI updates."""
            self._ensure_initialized()

            key_value = key.value if isinstance(key, NavigationCommand) else str(key)
            await self.client.call_tool("press_key", {"key": key_value, "times": 1})

            delay_ms = tab_delay_ms if "Tab" in key_value else expand_delay_ms
            if delay_ms > 0:
                await self.wait_ms(delay_ms)

        async def wait_ms(self, ms: int) -> None:
            """Wait in the active executor page."""
            self._ensure_initialized()
            if ms > 0:
                await self.client.call_tool("wait_ms", {"ms": ms})

        async def goto(self, url: str) -> None:
            """Navigate the active executor page to the given URL."""
            self._ensure_initialized()
            await self.client.call_tool("navigate", {"url": url})
            self._current_url = await self._read_current_url(default=url)

        async def refresh_page(self) -> None:
            """Reload the active executor page."""
            self._ensure_initialized()
            await self.client.call_tool("refresh", {})
            await self._refresh_current_url()

        async def evaluate(self, expression: str) -> Any:
            """Evaluate JavaScript in the active executor page."""
            self._ensure_initialized()
            return await self.client.call_tool("evaluate", {"js": expression})

        async def add_script(self, content: str) -> dict[str, Any]:
            """Inject JavaScript source into the active executor page."""
            self._ensure_initialized()
            payload = await self.client.call_tool("add_script", {"content": content})
            return payload if isinstance(payload, dict) else {"injected": True}

        async def get_page_html(self) -> tuple[str, str]:
            """Return the current page HTML and URL."""
            self._ensure_initialized()
            raw_html = await self.evaluate("() => document.documentElement.outerHTML")
            if isinstance(raw_html, dict):
                raw_html = (
                    raw_html.get("html")
                    or raw_html.get("source")
                    or raw_html.get("value")
                    or raw_html.get("result")
                )
            html = raw_html if isinstance(raw_html, str) else ""
            url = await self._read_current_url()
            return html, url

        async def get_page_metadata(self) -> dict[str, Any]:
            """Return serializable metadata for the active executor page."""
            self._ensure_initialized()
            payload = await self.client.call_tool("get_page_metadata", {})
            if not isinstance(payload, dict):
                return {"page_url": self._current_url, "page_title": "", "context_page_count": None}
            if payload.get("page_url"):
                self._current_url = str(payload["page_url"])
            return payload

        async def get_current_url(self) -> str:
            """Return the current URL, refreshing from executor metadata when possible."""
            if not self.is_initialized():
                return ""
            return await self._read_current_url(default=self._current_url)

        async def get_active_element_info(
            self,
            *,
            include_ax: bool = True,
            include_page_screenshot: bool = True,
            include_element_screenshot: bool = True,
            screenshot_margin: int = 50,
            html_max_length: int = 400,
        ) -> dict[str, Any] | None:
            """Return a serializable snapshot of document.activeElement."""
            self._ensure_initialized()
            payload = await self.client.call_tool(
                "get_active_element_info",
                {
                    "include_ax": include_ax,
                    "include_page_screenshot": include_page_screenshot,
                    "include_element_screenshot": include_element_screenshot,
                    "screenshot_margin": screenshot_margin,
                    "html_max_length": html_max_length,
                },
            )
            if not isinstance(payload, dict):
                return None
            if payload.get("page_url"):
                self._current_url = str(payload["page_url"])
            return payload

        async def close_session(self) -> None:
            """Close the executor browser session and transport."""
            try:
                if self.is_initialized():
                    await self.client.call_tool("close_session", {})
            finally:
                self._initialized = False
                self._current_url = ""
                await self.client.close()

        async def _refresh_current_url(self) -> None:
            self._current_url = await self._read_current_url(default=self._current_url)

        async def _read_current_url(self, default: str = "") -> str:
            try:
                metadata = await self.get_page_metadata()
                url = metadata.get("page_url") or metadata.get("url") or default
                self._current_url = str(url or "")
                return self._current_url
            except Exception:
                logger.debug("Unable to refresh current URL from executor metadata", exc_info=True)
                return default

        def _ensure_initialized(self) -> None:
            if not self.is_initialized():
                raise RuntimeError("Browser executor session not initialized")


BROWSER_SESSION = BrowserSession()
