"""MCP server exposing mobile accessibility testing tools.

Tools exposed:
- run_full_mobile_test(...): run the mobile accessibility test flow.
- get_report_file(report_id, file_type): retrieve a saved JSON, PowerPoint, or Excel report file.
"""

# ruff: noqa: E402

import argparse
import base64
from typing import Any, Literal

from dotenv import load_dotenv

load_dotenv()

from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from common import MobileContextKey
from tools.mobile_accessibility_service import (
    MobileAccessibilityScanRequest,
    MobileAccessibilityScanResult,
    run_mobile_accessibility_scan,
)
from tools.mobile_saver_tool import run_save_mobile
from utils.mobile_capabilities import discover_mobile_capabilities
from utils.report_store import (
    build_report_manifest,
    get_report_file_metadata,
    get_report_file_spec,
    read_report_file,
    read_report_json,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000

mcp = FastMCP(
    "MyServer",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


def _text_content_mcp(text: str) -> mcp_types.TextContent:
    return mcp_types.TextContent(type="text", text=text)


def _error_result(message: str, structured_content: dict[str, Any]) -> mcp_types.CallToolResult:
    return mcp_types.CallToolResult(
        isError=True,
        content=[_text_content_mcp(message)],
        structuredContent={"status": "error", "error": message, **structured_content},
    )


def _report_link(metadata: dict[str, Any]) -> mcp_types.ResourceLink:
    return mcp_types.ResourceLink(
        type="resource_link",
        name=metadata["filename"],
        uri=metadata["uri"],
        mimeType=metadata["mime_type"],
        size=metadata["size_bytes"],
    )


def _report_link_content(
    report_id: str, file_type: str, message: str
) -> tuple[list[mcp_types.ContentBlock], dict]:
    metadata = get_report_file_metadata(report_id, file_type)
    return [_text_content_mcp(message), _report_link(metadata)], metadata


def _report_embedded_content(
    report_id: str, file_type: str, message: str
) -> tuple[list[mcp_types.ContentBlock], dict[str, Any]]:
    content, metadata = read_report_file(report_id, file_type)
    spec = get_report_file_spec(file_type)
    resource_data = {"uri": metadata["uri"], "mimeType": metadata["mime_type"]}
    resource = (
        mcp_types.BlobResourceContents(blob=base64.b64encode(content).decode("ascii"), **resource_data)
        if spec.is_binary
        else mcp_types.TextResourceContents(text=content.decode("utf-8"), **resource_data)
    )
    return [
        _text_content_mcp(message),
        _report_link(metadata),
        mcp_types.EmbeddedResource(type="resource", resource=resource),
    ], metadata


def _build_mobile_scan_result(result: dict[str, Any]) -> mcp_types.CallToolResult:
    report_artifact = result.get("report_artifact")
    if not isinstance(report_artifact, dict) or not report_artifact.get("report_id"):
        return _error_result(
            "The accessibility test completed without a saved report artifact.",
            {
                "current_url": result.get("current_url"),
                "final_response": result.get("final_response", ""),
            },
        )

    report_id = report_artifact["report_id"]

    try:
        content, json_metadata = _report_embedded_content(
            report_id,
            "json",
            f"Accessibility test completed. Report id: {report_id}. JSON report attached.",
        )
        report = read_report_json(report_id)
    except (FileNotFoundError, ValueError, OSError) as exc:
        return _error_result(
            f"The test saved report_id {report_id}, but the JSON report could not be loaded: {exc}",
            {
                "current_url": result.get("current_url"),
                "report_id": report_id,
                "report_artifact": report_artifact,
            },
        )

    return mcp_types.CallToolResult(
        content=content,
        structuredContent={
            "status": result.get("status", "ok"),
            "current_url": result.get("current_url"),
            "final_response": result.get("final_response", ""),
            "activities": result.get("activities", 0),
            "report_id": report_id,
            "available_file_types": report_artifact.get("available_file_types", []),
            "files": report_artifact.get("files", []),
            "json_file": json_metadata,
            "report": report,
        },
    )


ReportFileType = Literal["json", "powerpoint", "excel"]


# --- MCP TOOLS ---
@mcp.tool()
async def get_test_capabilities() -> dict[str, Any]:
    """Return locally visible test capabilities."""
    return {"capabilities": discover_mobile_capabilities()}


@mcp.tool(structured_output=False)
async def run_full_mobile_test(
    app_package: str,
    app_activity: str,
    capability_id: str | None = None,
    max_steps: int = 500,
    max_activities: int = 20,
    max_depth: int = 10,
) -> mcp_types.CallToolResult:
    """Run the mobile accessibility flow using explicit app package/activity arguments.

    Parameters:
        app_package: Required. The package name of the target mobile application to test.
        app_activity: Required. The main activity of the target mobile application to test.
        capability_id: Optional. The ID of the mobile device capability to use for testing.
            If not provided, the tool will attempt to discover a single available capability.
        max_steps: Optional. The maximum number of steps to perform during the test.
        max_activities: Optional. The maximum number of unique activities to visit during the test.
        max_depth: Optional. The maximum navigation depth from the initial mobile screen.
    Only `app_package` and `app_activity` are required.
    Optional arguments should be supplied only when the caller wants to override the documented defaults,
    although MCP clients may still include default-valued arguments in the tool call.
    """
    app_package = app_package.strip()
    app_activity = app_activity.strip().lstrip("/")
    capability_id = capability_id.strip() if capability_id else None
    if not app_package or not app_activity:
        return _error_result("app_package and app_activity are required.", {})

    capabilities = discover_mobile_capabilities()
    if capability_id is None:
        if len(capabilities) != 1:
            return _error_result(
                "Expected exactly one local mobile capability. Pass capability_id explicitly.",
                {"capabilities": capabilities},
            )
        capability_id = str(capabilities[0]["id"])

    try:
        platform = _detect_mobile_platform(capabilities, capability_id)
        request = MobileAccessibilityScanRequest(
            app_package=app_package,
            app_activity=app_activity,
            capability_id=capability_id,
            platform=platform,
            max_steps=max_steps,
            max_activities=max_activities,
            max_depth=max_depth,
        )
        scan_result = await run_mobile_accessibility_scan(request)
        result = _mcp_scan_result(request, scan_result)
        result["report_artifact"] = run_save_mobile(_scan_state(request, scan_result))
        return _build_mobile_scan_result(result)
    except Exception as exc:
        return _error_result(str(exc), {"capability_id": capability_id})


def _mcp_scan_result(
    request: MobileAccessibilityScanRequest,
    scan_result: MobileAccessibilityScanResult,
) -> dict[str, object]:
    return {
        "status": "success",
        "activities": scan_result.activities,
        "current_url": f"mobile://{request.app_package}/{request.app_activity}",
        "final_response": "Mobile navigation and static analysis completed.",
    }


def _scan_state(
    request: MobileAccessibilityScanRequest,
    scan_result: MobileAccessibilityScanResult,
) -> dict[MobileContextKey, object]:
    return {
        MobileContextKey.APP_PACKAGE: request.app_package,
        MobileContextKey.APP_ACTIVITY: request.app_activity,
        MobileContextKey.CAPABILITY_ID: request.capability_id,
        MobileContextKey.NAVIGATOR_DATA: scan_result.navigator_data,
        MobileContextKey.STATIC_RESULTS: scan_result.static_results,
        MobileContextKey.STATIC_DEBUG_DATA: scan_result.static_debug_data,
    }


def _detect_mobile_platform(
    capabilities: list[dict[str, object]], capability_id: str
) -> Literal["Android", "iOS"]:
    """Resolve the supported platform of the selected mobile capability."""
    capability = next(
        (candidate for candidate in capabilities if candidate.get("id") == capability_id),
        None,
    )
    if not capability:
        raise ValueError(f"Mobile capability {capability_id!r} is not available.")

    platform = str(capability.get("platform") or "").casefold()
    if platform == "android":
        return "Android"
    if platform == "ios":
        return "iOS"
    raise ValueError(f"Unsupported mobile platform {platform or 'unknown'} for capability {capability_id!r}.")


@mcp.tool(structured_output=False)
async def get_report_file(report_id: str, file_type: ReportFileType) -> mcp_types.CallToolResult:
    """Retrieve a saved report file using explicit tool arguments.

    Parameters:
        report_id: Required. Report identifier returned by `run_full_mobile_test`.
        file_type: Required. File format to retrieve. Must be exactly one of
            "json", "powerpoint", or "excel".

    This tool has no optional arguments or defaults; both parameters must be
    provided by the caller.
    """
    try:
        content, metadata = _report_link_content(
            report_id,
            file_type,
            f"Retrieved {file_type} report file for report_id {report_id}.",
        )
        return mcp_types.CallToolResult(
            content=content,
            structuredContent={
                "status": "ok",
                "report_id": report_id,
                "file_type": file_type,
                "file": metadata,
                "available_file_types": build_report_manifest(report_id).get("available_file_types", []),
            },
        )
    except (FileNotFoundError, ValueError, OSError) as exc:
        return _error_result(str(exc), {"report_id": report_id, "file_type": file_type})


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the MCP server.")
    parser.add_argument("--host", default=DEFAULT_HOST, help="Host interface to bind.")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="Port to listen on.")

    args = parser.parse_args()
    mcp.settings.host = args.host
    mcp.settings.port = args.port

    mcp.run(transport="streamable-http")
