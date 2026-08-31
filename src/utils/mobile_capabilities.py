import os
import subprocess
from pathlib import Path

MOBILE_CAPABILITY_ID_ENV = "MOBILE_CAPABILITY_ID"
MOBILE_DEVICE_NAME_ENV = "MOBILE_DEVICE_NAME"
MOBILE_DEVICE_SERIAL_ENV = "MOBILE_DEVICE_SERIAL"
MOBILE_PLATFORM_ENV = "MOBILE_PLATFORM"
MOBILE_PLATFORM_VERSION_ENV = "MOBILE_PLATFORM_VERSION"
ANDROID_HOME_ENV = "ANDROID_HOME"
ANDROID_SDK_ROOT_ENV = "ANDROID_SDK_ROOT"


def _adb_bin() -> str:
    sdk_root = (
        os.getenv(ANDROID_HOME_ENV)
        or os.getenv(ANDROID_SDK_ROOT_ENV)
        or Path(__file__).resolve().parents[2] / "android-sdk"
    )
    adb = Path(sdk_root) / "platform-tools" / "adb"
    return str(adb) if adb.exists() else "adb"


def _adb(args: list[str], serial: str | None = None) -> str:
    cmd = [_adb_bin(), *(["-s", serial] if serial else []), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=False).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _prop(serial: str, key: str) -> str:
    return _adb(["shell", "getprop", key], serial)


def _android_capability(
    serial: str = "",
    capability_id: str | None = None,
    name: str | None = None,
) -> dict[str, object]:
    model = (_prop(serial, "ro.product.model") if serial else "") or os.getenv(MOBILE_DEVICE_NAME_ENV, "")
    manufacturer = _prop(serial, "ro.product.manufacturer") if serial else ""
    android_version = (_prop(serial, "ro.build.version.release") if serial else "") or os.getenv(
        MOBILE_PLATFORM_VERSION_ENV, ""
    )
    return {
        "id": capability_id or (f"local-android:{serial}" if serial else "mobile-android:configured"),
        "name": name or " ".join(part for part in [manufacturer, model] if part).strip() or serial,
        "type": "mobile",
        "platform": "android",
        "backend": "local-appium",
        "status": "available",
        "device_serial": serial,
        "metadata": {
            "model": model,
            "manufacturer": manufacturer,
            "android_version": android_version,
            "automation_name": "UiAutomator2",
        },
    }


def discover_mobile_capabilities() -> list[dict[str, object]]:
    if os.getenv(MOBILE_PLATFORM_ENV, "android").strip().lower() != "android":
        return []

    serial = os.getenv(MOBILE_DEVICE_SERIAL_ENV, "").strip()
    configured_name = os.getenv(MOBILE_DEVICE_NAME_ENV, "").strip()
    configured_id = os.getenv(MOBILE_CAPABILITY_ID_ENV, "").strip()
    if serial or configured_name or configured_id:
        return [
            _android_capability(
                serial,
                configured_id or None,
                configured_name or None,
            )
        ]

    capabilities = []
    for line in _adb(["devices", "-l"]).splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue

        capabilities.append(_android_capability(parts[0]))
    return capabilities
