import asyncio
import logging
import os
import re
import subprocess
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

logger = logging.getLogger(__name__)

APPIUM_SERVER_URL_ENV = "APPIUM_SERVER_URL"
ANDROID_SDK_ROOT_ENV = "ANDROID_SDK_ROOT"
APPIUM_HOME_ENV = "APPIUM_HOME"
DEFAULT_APPIUM_SERVER_URL = "http://127.0.0.1:4723"
APPIUM_AUTOSTART = True
APPIUM_LOG_PATH = "logs/appium.log"
MOBILE_NO_RESET = True
MOBILE_FULL_RESET = False
MOBILE_ADB_EXEC_TIMEOUT = 120000
MOBILE_UIAUTOMATOR2_SERVER_INSTALL_TIMEOUT = 120000
MOBILE_UIAUTOMATOR2_SERVER_LAUNCH_TIMEOUT = 120000
MOBILE_NEW_COMMAND_TIMEOUT_SECONDS = 300
MOBILE_ACTION_DELAY_MS = 500
ANDROID_KEYCODES = {
    "back": 4,
    "tab": 61,
    "enter": 66,
    "dpad_up": 19,
    "dpad_down": 20,
    "dpad_left": 21,
    "dpad_right": 22,
    "dpad_center": 23,
}

_RUN_LOGS_DIR: Path | None = None
MOBILE_SESSION_LOCK = asyncio.Lock()


def _project_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _create_mobile_run_logs_dir(app_package: str | None = None) -> Path:
    logs_dir = _project_root() / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)
    package_label = "".join(
        char if char.isalnum() or char in "._-" else "_" for char in app_package or "mobile"
    ).strip("._-")
    run_name = f"{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}_{package_label or 'mobile'}"
    run_logs_dir = logs_dir / run_name
    suffix = 1
    while run_logs_dir.exists():
        run_logs_dir = logs_dir / f"{run_name}_{suffix}"
        suffix += 1
    run_logs_dir.mkdir(parents=True)
    return run_logs_dir


def get_mobile_run_logs_dir() -> Path:
    global _RUN_LOGS_DIR
    if _RUN_LOGS_DIR is None:
        _RUN_LOGS_DIR = _create_mobile_run_logs_dir()
    return _RUN_LOGS_DIR


def _appium_env() -> dict[str, str]:
    sdk_root = os.getenv(ANDROID_SDK_ROOT_ENV) or str(_project_root() / "android-sdk")
    env = os.environ.copy()
    env[ANDROID_SDK_ROOT_ENV] = sdk_root
    env[APPIUM_HOME_ENV] = str(_project_root())
    return env


def _log_path() -> Path:
    path = Path(APPIUM_LOG_PATH).expanduser()
    if not path.is_absolute():
        if path.parts and path.parts[0] == "logs":
            path = Path(*path.parts[1:]) if len(path.parts) > 1 else Path("appium.log")
        path = get_mobile_run_logs_dir() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    return path


class MobileSession:
    def __init__(self, server_url: str | None = None) -> None:
        self.server_url = server_url or os.getenv(APPIUM_SERVER_URL_ENV) or DEFAULT_APPIUM_SERVER_URL
        self.driver = None
        self.server_process: subprocess.Popen | None = None
        self.app_package: str | None = None
        self.app_activity: str | None = None

    def is_initialized(self) -> bool:
        return self.driver is not None

    async def connect(
        self,
        capability_id: str,
        *,
        app_package: str | None = None,
        app_activity: str | None = None,
    ) -> None:
        serial = (
            capability_id.removeprefix("local-android:") if capability_id.startswith("local-android:") else ""
        )
        global _RUN_LOGS_DIR
        _RUN_LOGS_DIR = _create_mobile_run_logs_dir(app_package)

        def _connect():
            from appium import webdriver
            from appium.options.android import UiAutomator2Options

            options = UiAutomator2Options()
            options.set_capability("platformName", "Android")
            options.set_capability("appium:automationName", "UiAutomator2")
            options.set_capability("appium:noReset", MOBILE_NO_RESET)
            options.set_capability("appium:fullReset", MOBILE_FULL_RESET)
            options.set_capability("appium:adbExecTimeout", MOBILE_ADB_EXEC_TIMEOUT)
            options.set_capability(
                "appium:uiautomator2ServerInstallTimeout", MOBILE_UIAUTOMATOR2_SERVER_INSTALL_TIMEOUT
            )
            options.set_capability(
                "appium:uiautomator2ServerLaunchTimeout", MOBILE_UIAUTOMATOR2_SERVER_LAUNCH_TIMEOUT
            )
            options.set_capability("appium:newCommandTimeout", MOBILE_NEW_COMMAND_TIMEOUT_SECONDS)
            options.set_capability("appium:skipServerInstallation", False)
            if app_package:
                options.set_capability("appium:forceAppLaunch", True)
            for key, value in {
                "appium:udid": serial,
                "appium:appPackage": app_package,
                "appium:appActivity": app_activity,
            }.items():
                if value:
                    options.set_capability(key, value)
            return webdriver.Remote(self.server_url, options=options)

        await self._ensure_server()
        await self.disconnect()
        self.app_package = app_package
        self.app_activity = app_activity
        self.driver = await asyncio.to_thread(_connect)
        await self._restart_configured_app()

    async def disconnect(self) -> None:
        driver = self.driver
        self.driver = None
        self.app_package = None
        self.app_activity = None
        if driver is not None:
            try:
                await asyncio.to_thread(driver.quit)
            except Exception:
                logger.debug("Appium session was already closed", exc_info=True)

    async def terminate_app(self, package_name: str) -> None:
        await asyncio.to_thread(self._driver.terminate_app, package_name)

    async def get_window_size(self) -> dict[str, int]:
        return await asyncio.to_thread(self._driver.get_window_size)

    # Mobile primitive to navigate the device, both for touch and key events.
    # These are used to simulate user interactions with the device.
    async def tap(self, x: int, y: int) -> None:
        await asyncio.to_thread(self._driver.tap, [(int(x), int(y))])
        await self._wait_after_action()

    async def tap_bounds(self, bounds: str) -> None:
        left, top, right, bottom = map(int, re.findall(r"\d+", bounds)[:4])
        await self.tap((left + right) // 2, (top + bottom) // 2)

    async def tap_center(self) -> None:
        size = await self.get_window_size()
        await self.tap(size["width"] // 2, size["height"] // 2)

    async def swipe(self, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 500) -> None:
        await asyncio.to_thread(
            self._driver.swipe,
            int(start_x),
            int(start_y),
            int(end_x),
            int(end_y),
            int(duration_ms),
        )
        await self._wait_after_action()

    async def scroll_down(self) -> None:
        size = await self.get_window_size()
        x = size["width"] // 2
        await self.swipe(x, int(size["height"] * 0.8), x, int(size["height"] * 0.25))

    async def scroll_up(self) -> None:
        size = await self.get_window_size()
        x = size["width"] // 2
        await self.swipe(x, int(size["height"] * 0.25), x, int(size["height"] * 0.8))

    async def swipe_left(self) -> None:
        size = await self.get_window_size()
        y = size["height"] // 2
        await self.swipe(int(size["width"] * 0.8), y, int(size["width"] * 0.2), y)

    async def swipe_right(self) -> None:
        size = await self.get_window_size()
        y = size["height"] // 2
        await self.swipe(int(size["width"] * 0.2), y, int(size["width"] * 0.8), y)

    async def press_keycode(self, keycode: int) -> None:
        await asyncio.to_thread(self._driver.press_keycode, int(keycode))
        await self._wait_after_action()

    async def press_key(self, key: str) -> None:
        await self.press_keycode(ANDROID_KEYCODES[key.lower()])

    async def back(self) -> None:
        await self.press_key("back")

    async def press_tab(self) -> None:
        await self.press_key("tab")

    async def press_enter(self) -> None:
        await self.press_key("enter")

    async def press_dpad_up(self) -> None:
        await self.press_key("dpad_up")

    async def press_dpad_down(self) -> None:
        await self.press_key("dpad_down")

    async def press_dpad_left(self) -> None:
        await self.press_key("dpad_left")

    async def press_dpad_right(self) -> None:
        await self.press_key("dpad_right")

    async def press_dpad_center(self) -> None:
        await self.press_key("dpad_center")

    #################################################################

    async def _ensure_server(self) -> None:
        if self._server_ready() or not APPIUM_AUTOSTART:
            return
        parsed = urlparse(self.server_url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            return
        log_file = _log_path().open("a", encoding="utf-8")
        appium_bin = _project_root() / "node_modules" / ".bin" / "appium"
        self.server_process = subprocess.Popen(
            [
                str(appium_bin),
                "--address",
                parsed.hostname or "127.0.0.1",
                "--port",
                str(parsed.port or 4723),
                "--allow-insecure",
                "uiautomator2:adb_shell",
            ],
            cwd=_project_root(),
            stdout=log_file,
            stderr=log_file,
            env=_appium_env(),
        )
        for _ in range(30):
            if self._server_ready():
                return
            if self.server_process.poll() is not None:
                raise RuntimeError(f"Appium server failed to start. Check {_log_path()}.")
            await asyncio.to_thread(time.sleep, 1)

    def _server_ready(self) -> bool:
        try:
            with urlopen(f"{self.server_url.rstrip('/')}/status", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    async def _wait_after_action(self) -> None:
        await asyncio.sleep(MOBILE_ACTION_DELAY_MS / 1000)

    async def get_accessibility_tree(self) -> str:
        return await asyncio.to_thread(lambda: self._driver.page_source)

    async def take_screenshot(self) -> str:
        return await asyncio.to_thread(self._driver.get_screenshot_as_base64)

    async def get_device_metadata(self) -> dict[str, Any]:
        return await asyncio.to_thread(lambda: dict(self._driver.capabilities))

    async def get_current_package(self) -> str:
        return await asyncio.to_thread(lambda: str(self._driver.current_package or ""))

    async def get_current_activity(self) -> str:
        return await asyncio.to_thread(lambda: str(self._driver.current_activity or ""))

    async def ensure_app_foreground(self) -> None:
        if not self.app_package:
            return
        if await self.get_current_package() == self.app_package:
            return

        await asyncio.to_thread(self._launch_configured_app)
        for _ in range(10):
            if await self.get_current_package() == self.app_package:
                return
            await asyncio.sleep(0.5)

        current_package = await self.get_current_package()
        current_activity = await self.get_current_activity()
        raise RuntimeError(
            "Requested app is not in foreground after launch. "
            f"expected={self.app_package}, actual={current_package}/{current_activity}"
        )

    async def _restart_configured_app(self) -> None:
        if not self.app_package:
            return

        await asyncio.to_thread(self._terminate_configured_app)
        await self._clear_recent_app()
        await asyncio.to_thread(self._launch_configured_app_fresh)
        await self.ensure_app_foreground()

    def _terminate_configured_app(self) -> None:
        terminate_app = getattr(self._driver, "terminate_app", None)
        if callable(terminate_app):
            try:
                terminate_app(self.app_package)
                return
            except Exception:
                logger.debug("Appium terminate_app failed; falling back to mobile shell", exc_info=True)

        self._execute_mobile_shell("am", ["force-stop", self.app_package])

    async def _clear_recent_app(self) -> None:
        app_switch_opened = False
        try:
            await asyncio.to_thread(
                self._execute_mobile_shell,
                "input",
                ["keyevent", "KEYCODE_APP_SWITCH"],
            )
            app_switch_opened = True
            await asyncio.sleep(0.25)
            await asyncio.to_thread(
                self._execute_mobile_shell,
                "input",
                ["keyevent", "KEYCODE_DEL"],
            )
            return
        except Exception:
            logger.debug("Mobile shell recents cleanup failed; falling back to Appium keycodes", exc_info=True)

        try:
            if not app_switch_opened:
                await asyncio.to_thread(self._driver.press_keycode, 187)
                await asyncio.sleep(0.25)
            await asyncio.to_thread(self._driver.press_keycode, 67)
        except Exception:
            logger.debug("Unable to clear the app from recents", exc_info=True)

    def _launch_configured_app_fresh(self) -> None:
        component = self._configured_component()
        if component:
            try:
                self._execute_mobile_shell("am", ["start", "-n", component])
                return
            except Exception:
                logger.debug("Mobile shell launch failed; falling back to Appium launch", exc_info=True)
        self._launch_configured_app()

    def _configured_component(self) -> str | None:
        if not self.app_package or not self.app_activity:
            return None
        if "/" in self.app_activity:
            return self.app_activity
        activity = self.app_activity
        if not activity.startswith(".") and "." not in activity:
            activity = f".{activity}"
        return f"{self.app_package}/{activity}"

    def _execute_mobile_shell(self, command: str, args: list[str]) -> Any:
        return self._driver.execute_script("mobile: shell", {"command": command, "args": args})

    def _launch_configured_app(self) -> None:
        driver = self._driver
        if self.app_package and self.app_activity:
            activity = self.app_activity
            if not activity.startswith(".") and "/" not in activity and "." not in activity:
                activity = f".{activity}"
            try:
                driver.start_activity(self.app_package, activity)
                return
            except Exception:
                pass

        if self.app_package:
            driver.activate_app(self.app_package)

    @property
    def _driver(self):
        if self.driver is None:
            raise RuntimeError("Mobile session not initialized")
        return self.driver


MOBILE_SESSION = MobileSession()


@asynccontextmanager
async def mobile_session(
    capability_id: str,
    app_package: str,
    app_activity: str,
) -> AsyncIterator[MobileSession]:
    """Provide exclusive ownership of a connected mobile application session."""
    async with MOBILE_SESSION_LOCK:
        try:
            await MOBILE_SESSION.connect(
                capability_id,
                app_package=app_package,
                app_activity=app_activity,
            )
            yield MOBILE_SESSION
        finally:
            try:
                await MOBILE_SESSION.terminate_app(app_package)
            except Exception:
                logger.warning("Unable to terminate app %s", app_package, exc_info=True)
            await MOBILE_SESSION.disconnect()
