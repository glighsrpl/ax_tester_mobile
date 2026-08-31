import base64
import logging
import re
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from playwright.async_api import (
    Browser,
    BrowserContext,
    CDPSession,
    ElementHandle,
    Page,
    Playwright,
    async_playwright,
)

logger = logging.getLogger(__name__)

_EMPTY_AX: dict[str, Any] = {"role": None, "name": None, "description": None, "properties": {}}

if TYPE_CHECKING:
    from utils.browser_session import NavigationCommand


async def release_remote_object(cdp: CDPSession, object_id: str | None) -> None:
    """Release a Runtime objectId if present, ignoring errors."""
    if not object_id:
        return
    try:
        await cdp.send("Runtime.releaseObject", {"objectId": object_id})
    except Exception:
        pass


async def delete_global_key(cdp: CDPSession, key: str) -> None:
    """Delete a globalThis key if present, ignoring errors."""
    try:
        await cdp.send(
            "Runtime.evaluate",
            {"expression": f"delete globalThis[{key!r}]", "returnByValue": True},
        )
    except Exception:
        pass


async def get_backend_dom_node_id_for_object_id(cdp: CDPSession, object_id: str) -> int | None:
    """Return backendDOMNodeId for a given Runtime objectId via CDP."""
    try:
        desc = await cdp.send("DOM.describeNode", {"objectId": object_id})
        return desc.get("node", {}).get("backendNodeId")
    except Exception:
        return None


async def get_backend_dom_node_id(cdp: CDPSession, element: ElementHandle) -> int | None:
    """Return backendDOMNodeId for a Playwright element via CDP."""
    tmp_key = "__pw_backend_id_113"
    object_id: str | None = None
    try:
        await element.evaluate("(node, key) => { globalThis[key] = node; }", tmp_key)
        remote = await cdp.send(
            "Runtime.evaluate",
            {"expression": f"globalThis[{tmp_key!r}]", "returnByValue": False},
        )
        object_id = remote.get("result", {}).get("objectId")
        if not object_id:
            return None
        return await get_backend_dom_node_id_for_object_id(cdp, object_id)
    finally:
        await delete_global_key(cdp, tmp_key)
        await release_remote_object(cdp, object_id)


async def get_ax_info_cdp(cdp: CDPSession, element: ElementHandle) -> dict[str, Any]:
    """Fetch basic accessibility info for a Playwright element via CDP."""
    tmp_key = "__pw_ax_113"
    object_id: str | None = None

    try:
        await element.evaluate("(node, key) => { globalThis[key] = node; }", tmp_key)
        remote = await cdp.send(
            "Runtime.evaluate",
            {"expression": f"globalThis[{tmp_key!r}]", "returnByValue": False},
        )
        object_id = remote.get("result", {}).get("objectId")
        if not object_id:
            return dict(_EMPTY_AX)

        ax = await cdp.send(
            "Accessibility.getPartialAXTree",
            {"objectId": object_id, "fetchRelatives": False},
        )
        nodes = ax.get("nodes", [])
        if not nodes:
            return dict(_EMPTY_AX)

        target = nodes[0]
        if len(nodes) > 1:
            backend_node_id = await get_backend_dom_node_id_for_object_id(cdp, object_id)
            if backend_node_id is not None:
                for node in nodes:
                    if node.get("backendDOMNodeId") == backend_node_id:
                        target = node
                        break

        properties = {}
        for prop in target.get("properties", []):
            value = prop.get("value", {}).get("value")
            properties[prop.get("name")] = value

        return {
            "role": target.get("role", {}).get("value"),
            "name": target.get("name", {}).get("value"),
            "description": target.get("description", {}).get("value"),
            "properties": properties,
        }
    except Exception:
        logger.error("Unable to extract ax info from element %s", element, exc_info=True)
        return dict(_EMPTY_AX)
    finally:
        await delete_global_key(cdp, tmp_key)
        await release_remote_object(cdp, object_id)


def _to_base64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


async def get_page_screenshot(page: Page) -> str | None:
    """Return a full-page PNG screenshot as raw base64."""
    try:
        return _to_base64(await page.screenshot(full_page=True, type="png"))
    except Exception:
        logger.debug("Unable to capture page screenshot", exc_info=True)
        return None


async def get_element_screenshot(page: Page, element: ElementHandle, margin: int = 50) -> str | None:
    """Return a margin-expanded element PNG screenshot as raw base64."""
    try:
        try:
            await element.scroll_into_view_if_needed(timeout=2000)
        except Exception:
            logger.debug("Unable to scroll active element into view before screenshot", exc_info=True)

        box = await element.bounding_box()
        if not box or box.get("width", 0) <= 0 or box.get("height", 0) <= 0:
            return None

        safe_margin = max(0, int(margin))
        metrics = await page.evaluate("""() => ({width: window.innerWidth, height: window.innerHeight})""")
        page_width = float(metrics.get("width") or box["x"] + box["width"])
        page_height = float(metrics.get("height") or box["y"] + box["height"])

        x = max(0.0, float(box["x"]) - safe_margin)
        y = max(0.0, float(box["y"]) - safe_margin)
        right = min(page_width, float(box["x"]) + float(box["width"]) + safe_margin)
        bottom = min(page_height, float(box["y"]) + float(box["height"]) + safe_margin)
        width = right - x
        height = bottom - y
        if width <= 0 or height <= 0:
            return None

        return _to_base64(
            await page.screenshot(
                type="png",
                clip={"x": x, "y": y, "width": width, "height": height},
            )
        )
    except Exception:
        logger.debug("Unable to capture clipped element screenshot; trying element screenshot", exc_info=True)
        try:
            return _to_base64(await element.screenshot(type="png"))
        except Exception:
            logger.debug("Unable to capture element screenshot", exc_info=True)
            return None


class BrowserSessionLocal:
    """Facade over a local Playwright Chromium session."""

    def __init__(
        self,
        *,
        headless: bool = False,
        navigation_settle_ms: int = 500,
        networkidle_timeout_ms: int = 5000,
    ) -> None:
        self.headless = headless
        self.navigation_settle_ms = navigation_settle_ms
        self.networkidle_timeout_ms = networkidle_timeout_ms
        self.session_id: str | None = None
        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self._page: Page | None = None
        self._cdp: CDPSession | None = None
        self._initialized = False
        self._current_url = ""

    def is_initialized(self) -> bool:
        """Return True when a local Playwright browser session has been created."""
        return (
            self._initialized
            and self._playwright is not None
            and self._browser is not None
            and self._browser.is_connected()
            and self._context is not None
            and self._page is not None
            and not self._page.is_closed()
            and self._cdp is not None
        )

    async def create_session(self, session_id: str | None = None) -> None:
        """Create a fresh local Playwright browser session."""
        if self.is_initialized():
            await self.close_session()

        self.session_id = session_id
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(channel="chrome", headless=self.headless)
            self._context = await self._browser.new_context()
            self._page = await self._context.new_page()
            await self._page.goto("about:blank", wait_until="domcontentloaded")
            self._cdp = await self._context.new_cdp_session(self._page)
            self._initialized = True
            await self._refresh_current_url()
        except Exception:
            await self.close_session()
            raise

    async def press_key(
        self, key: "NavigationCommand | str", tab_delay_ms: int = 50, expand_delay_ms: int = 1000
    ) -> None:
        """Press a keyboard key on the active local page and wait for UI updates."""
        page = self._get_page()
        key_value = key.value if isinstance(key, StrEnum) else str(key)
        await page.keyboard.press(key_value)

        delay_ms = tab_delay_ms if "Tab" in key_value else expand_delay_ms
        if delay_ms > 0:
            await self.wait_ms(delay_ms)

    async def wait_ms(self, ms: int) -> None:
        """Wait in the active local page."""
        page = self._get_page()
        if ms > 0:
            await page.wait_for_timeout(ms)

    async def goto(self, url: str) -> None:
        """Navigate the active local page to the given URL."""
        page = self._get_page()
        await page.goto(url, wait_until="domcontentloaded")
        await self._wait_for_load_stability()
        self._current_url = page.url

    async def refresh_page(self) -> None:
        """Reload the active local page."""
        page = self._get_page()
        await page.reload(wait_until="domcontentloaded")
        await self._wait_for_load_stability()
        await self._refresh_current_url()

    async def evaluate(self, expression: str) -> Any:
        """Evaluate JavaScript in the active local page."""
        page = self._get_page()
        return await page.evaluate(expression)

    async def add_script(self, content: str) -> dict[str, Any]:
        """Inject JavaScript source into the active local page."""
        page = self._get_page()
        handle = await page.add_script_tag(content=content)
        await handle.dispose()
        return {"injected": True}

    async def get_page_html(self) -> tuple[str, str]:
        """Return the current page HTML and URL."""
        raw_html = await self.evaluate("() => document.documentElement.outerHTML")
        html = raw_html if isinstance(raw_html, str) else ""
        url = await self._read_current_url()
        return html, url

    async def get_page_metadata(self) -> dict[str, Any]:
        """Return serializable metadata for the active local page."""
        page = self._get_page()
        self._current_url = page.url
        return {
            "page_url": page.url,
            "page_title": await page.title(),
            "context_page_count": len(page.context.pages),
        }

    async def get_current_url(self) -> str:
        """Return the current URL, refreshing from the local page when possible."""
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
        page = self._get_page()
        cdp = self._get_cdp()
        handle = await page.evaluate_handle("() => document.activeElement")
        element = handle.as_element()
        if not element:
            await handle.dispose()
            return None

        try:
            outer_html = await element.evaluate("el => el.outerHTML")
            outer_html = re.sub(r"\s+", " ", str(outer_html or "")).strip()[:html_max_length]
            tag = await element.evaluate("el => el.tagName")
            href = await element.evaluate("el => el.getAttribute('href')")

            backend_dom_node_id = await get_backend_dom_node_id(cdp, element)
            ax_info = await get_ax_info_cdp(cdp, element) if include_ax else None
            element_screenshot = (
                await get_element_screenshot(page, element, screenshot_margin)
                if include_element_screenshot
                else None
            )
            page_screenshot = await get_page_screenshot(page) if include_page_screenshot else None
            page_url = page.url
            page_title = await page.title()
            self._current_url = page_url

            return {
                "backend_dom_node_id": backend_dom_node_id,
                "page_screenshot": page_screenshot,
                "element_screenshot": element_screenshot,
                "element_ax_info": ax_info,
                "element_out_html": outer_html,
                "element_html_tag": tag,
                "element_href": href,
                "page_url": page_url,
                "page_title": page_title,
                "context_page_count": len(page.context.pages),
            }
        finally:
            try:
                await element.dispose()
            finally:
                if element is not handle:
                    await handle.dispose()

    async def close_session(self) -> None:
        """Close the local Playwright browser session."""
        try:
            if self._cdp is not None:
                try:
                    await self._cdp.detach()
                except Exception:
                    logger.debug("Error while detaching local CDP session", exc_info=True)
            if self._page is not None and not self._page.is_closed():
                try:
                    await self._page.close()
                except Exception:
                    logger.debug("Error while closing local Playwright page", exc_info=True)
            if self._context is not None:
                try:
                    await self._context.close()
                except Exception:
                    logger.debug("Error while closing local Playwright context", exc_info=True)
            if self._browser is not None:
                try:
                    await self._browser.close()
                except Exception:
                    logger.debug("Error while closing local Playwright browser", exc_info=True)
            if self._playwright is not None:
                try:
                    await self._playwright.stop()
                except Exception:
                    logger.debug("Error while stopping local Playwright", exc_info=True)
        finally:
            self.session_id = None
            self._playwright = None
            self._browser = None
            self._context = None
            self._page = None
            self._cdp = None
            self._initialized = False
            self._current_url = ""

    async def _wait_for_load_stability(self) -> None:
        page = self._get_page()
        try:
            await page.wait_for_load_state("networkidle", timeout=self.networkidle_timeout_ms)
        except Exception:
            logger.debug("Timed out waiting for networkidle after navigation", exc_info=True)
        if self.navigation_settle_ms > 0:
            await page.wait_for_timeout(self.navigation_settle_ms)

    async def _refresh_current_url(self) -> None:
        self._current_url = await self._read_current_url(default=self._current_url)

    async def _read_current_url(self, default: str = "") -> str:
        try:
            page = self._get_page()
            self._current_url = str(page.url or "")
            return self._current_url
        except Exception:
            logger.debug("Unable to refresh current URL from local page", exc_info=True)
            return default

    def _get_page(self) -> Page:
        self._ensure_initialized()
        assert self._page is not None
        return self._page

    def _get_cdp(self) -> CDPSession:
        self._ensure_initialized()
        assert self._cdp is not None
        return self._cdp

    def _ensure_initialized(self) -> None:
        if not self.is_initialized():
            raise RuntimeError("Local browser session not initialized")
