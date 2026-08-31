import os
import subprocess
from pathlib import Path

ANDROID_HOME_ENV = "ANDROID_HOME"
ANDROID_SDK_ROOT_ENV = "ANDROID_SDK_ROOT"


def _adb_bin() -> str:
    sdk_root = (
        os.getenv(ANDROID_HOME_ENV)
        or os.getenv(ANDROID_SDK_ROOT_ENV)
        or Path(__file__).resolve().parents[3] / "android-sdk"
    )
    adb = Path(sdk_root) / "platform-tools" / "adb"
    return str(adb) if adb.exists() else "adb"


def _adb(args: list[str], serial: str | None = None) -> str:
    cmd = [_adb_bin(), *(["-s", serial] if serial else []), *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False).stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def _prop(serial: str, key: str) -> str:
    return _adb(["shell", "getprop", key], serial)


def _android_capability(
    serial: str,
    capability_id: str,
    name: str,
) -> dict[str, object]:
    model = _prop(serial, "ro.product.model")
    manufacturer = _prop(serial, "ro.product.manufacturer")
    android_version = _prop(serial, "ro.build.version.release")
    return {
        "id": capability_id,
        "name": name,
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
    capabilities = []
    for line in _adb(["devices", "-l"]).splitlines()[1:]:
        parts = line.split()
        if len(parts) < 2 or parts[1] != "device":
            continue

        serial = parts[0]
        details = dict(part.split(":", 1) for part in parts[2:] if ":" in part)
        name = details.get("model", "").replace("_", " ") or serial
        capabilities.append(_android_capability(serial, f"local-android:{serial}", name))
    return capabilities
