import asyncio
import os
import subprocess
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from urllib.request import urlopen

APPIUM_SERVER_URL_ENV = "APPIUM_SERVER_URL"
ANDROID_HOME_ENV = "ANDROID_HOME"
ANDROID_SDK_ROOT_ENV = "ANDROID_SDK_ROOT"
APPIUM_HOME_ENV = "APPIUM_HOME"
DEFAULT_APPIUM_SERVER_URL = "http://127.0.0.1:4723"
MOBILE_DEVICE_NAME_ENV = "MOBILE_DEVICE_NAME"
MOBILE_DEVICE_SERIAL_ENV = "MOBILE_DEVICE_SERIAL"
MOBILE_PLATFORM_VERSION_ENV = "MOBILE_PLATFORM_VERSION"
APPIUM_AUTOSTART = True
APPIUM_LOG_PATH = "logs/appium.log"
MOBILE_NO_RESET = True
MOBILE_FULL_RESET = False
MOBILE_ADB_EXEC_TIMEOUT = 120000
MOBILE_UIAUTOMATOR2_SERVER_INSTALL_TIMEOUT = 120000
MOBILE_UIAUTOMATOR2_SERVER_LAUNCH_TIMEOUT = 120000


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _appium_env() -> dict[str, str]:
    sdk_root = os.getenv(ANDROID_HOME_ENV) or os.getenv(ANDROID_SDK_ROOT_ENV) or str(
        _project_root() / "android-sdk"
    )
    env = os.environ.copy()
    env[ANDROID_HOME_ENV] = sdk_root
    env[ANDROID_SDK_ROOT_ENV] = sdk_root
    env[APPIUM_HOME_ENV] = str(_project_root())
    env["PATH"] = os.pathsep.join([str(Path(sdk_root) / "platform-tools"), env.get("PATH", "")])
    return env


def _log_path() -> Path:
    path = Path(APPIUM_LOG_PATH).expanduser()
    if not path.is_absolute():
        path = _project_root() / path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch(exist_ok=True)
    return path


class MobileSession:
    def __init__(self, server_url: str | None = None) -> None:
        self.server_url = server_url or os.getenv(APPIUM_SERVER_URL_ENV) or DEFAULT_APPIUM_SERVER_URL
        self.driver = None
        self.server_process: subprocess.Popen | None = None

    def is_initialized(self) -> bool:
        return self.driver is not None

    async def connect(
        self,
        capability_id: str,
        *,
        app_package: str | None = None,
        app_activity: str | None = None,
    ) -> None:
        serial = capability_id.removeprefix("local-android:") if capability_id.startswith("local-android:") else ""
        serial = serial or os.getenv(MOBILE_DEVICE_SERIAL_ENV, "").strip()

        def _connect():
            from appium import webdriver
            from appium.options.android import UiAutomator2Options

            options = UiAutomator2Options()
            options.set_capability("platformName", "Android")
            options.set_capability("appium:automationName", "UiAutomator2")
            options.set_capability("appium:noReset", MOBILE_NO_RESET)
            options.set_capability("appium:fullReset", MOBILE_FULL_RESET)
            options.set_capability("appium:adbExecTimeout", MOBILE_ADB_EXEC_TIMEOUT)
            options.set_capability("appium:uiautomator2ServerInstallTimeout", MOBILE_UIAUTOMATOR2_SERVER_INSTALL_TIMEOUT)
            options.set_capability("appium:uiautomator2ServerLaunchTimeout", MOBILE_UIAUTOMATOR2_SERVER_LAUNCH_TIMEOUT)
            options.set_capability("appium:skipServerInstallation", False)
            for key, value in {
                "appium:udid": serial,
                "appium:deviceName": os.getenv(MOBILE_DEVICE_NAME_ENV),
                "appium:platformVersion": os.getenv(MOBILE_PLATFORM_VERSION_ENV),
                "appium:appPackage": app_package,
                "appium:appActivity": app_activity,
            }.items():
                if value:
                    options.set_capability(key, value)
            return webdriver.Remote(self.server_url, options=options)

        await self._ensure_server()
        await self.disconnect()
        self.driver = await asyncio.to_thread(_connect)

    async def disconnect(self) -> None:
        if self.driver is not None:
            driver = self.driver
            self.driver = None
            await asyncio.to_thread(driver.quit)

    async def _ensure_server(self) -> None:
        if self._server_ready() or not APPIUM_AUTOSTART:
            return
        parsed = urlparse(self.server_url)
        if parsed.hostname not in {"127.0.0.1", "localhost"}:
            return
        log_file = _log_path().open("a", encoding="utf-8")
        appium_bin = _project_root() / "node_modules" / ".bin" / "appium"
        self.server_process = subprocess.Popen(
            [str(appium_bin), "--address", parsed.hostname or "127.0.0.1", "--port", str(parsed.port or 4723)],
            cwd=_project_root(),
            stdout=log_file,
            stderr=log_file,
            env=_appium_env(),
        )
        for _ in range(30):
            if self._server_ready():
                return
            await asyncio.to_thread(time.sleep, 1)

    def _server_ready(self) -> bool:
        try:
            with urlopen(f"{self.server_url.rstrip('/')}/status", timeout=2) as response:
                return response.status == 200
        except Exception:
            return False

    async def get_accessibility_tree(self) -> str:
        return await asyncio.to_thread(lambda: self._driver.page_source)

    async def take_screenshot(self) -> str:
        return await asyncio.to_thread(self._driver.get_screenshot_as_base64)

    async def get_device_metadata(self) -> dict[str, Any]:
        return await asyncio.to_thread(lambda: dict(self._driver.capabilities))

    @property
    def _driver(self):
        if self.driver is None:
            raise RuntimeError("Mobile session not initialized")
        return self.driver


MOBILE_SESSION = MobileSession()
