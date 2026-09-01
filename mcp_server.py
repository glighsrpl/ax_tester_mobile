"""MCP server exposing the ADK root agent for accessibility testing.

Tools exposed:
- run_full_mobile_test(...): run the mobile accessibility test flow.
- get_report_file(report_id, file_type): retrieve a saved JSON, PowerPoint, or Excel report file.
"""

# ruff: noqa: E402

import argparse
import asyncio
import base64
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from dotenv import load_dotenv

load_dotenv()

from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from google.adk.utils.context_utils import Aclosing
from google.genai import types as genai_types
from mcp import types as mcp_types
from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from common import MobileContextKey
from mobile_agent import mobile_root_agent
from tools.mobile_saver_tool import run_save_mobile
from utils.mobile_capabilities import discover_mobile_capabilities
from utils.mobile_session import MOBILE_SESSION
from utils.report_store import (
    build_report_manifest,
    get_report_file_metadata,
    get_report_file_spec,
    read_report_file,
    read_report_json,
)

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
USER_ID = "mcp_user"

mcp = FastMCP(
    "MyServer",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False,
    ),
)


@dataclass
class MobileAgentBridge:
    """Run the ADK mobile root agent in an isolated MCP session."""

    session_service: InMemorySessionService = field(default_factory=InMemorySessionService)
    runner: Runner | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def run_turn(self, state: dict[str, Any]) -> dict[str, Any]:
        """Run one serialized ADK turn and return its resulting session state."""
        async with self.lock:
            try:
                return await self._run_turn_locked(state)
            finally:
                await MOBILE_SESSION.disconnect()

    async def _run_turn_locked(self, state: dict[str, Any]) -> dict[str, Any]:
        self._ensure_runner()
        session_id = str(uuid.uuid4())
        await self.session_service.create_session(
            app_name="mobile_ax_tester_mcp",
            user_id=USER_ID,
            session_id=session_id,
            state=state,
        )
        content = _mobile_test_request(state)
        events: list[Any] = []
        assert self.runner is not None
        async with Aclosing(
            self.runner.run_async(user_id=USER_ID, session_id=session_id, new_message=content)
        ) as event_stream:
            async for event in event_stream:
                events.append(event)

        return self._build_result(session_id, events, await self._load_state(session_id))

    def _ensure_runner(self) -> None:
        if self.runner is None:
            self.runner = Runner(
                app_name="mobile_ax_tester_mcp",
                agent=mobile_root_agent,
                session_service=self.session_service,
            )

    def _build_result(
        self,
        session_id: str,
        events: list[Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        messages: list[dict[str, str]] = []
        function_calls: list[dict[str, Any]] = []
        final_response = ""
        for event in events:
            if event.content and event.content.parts:
                message = "".join(part.text or "" for part in event.content.parts)
                if message.strip():
                    messages.append({"author": event.author or "unknown", "text": message})
                    if (event.author or "").lower() != "user":
                        final_response = message
            function_calls.extend(
                {"name": function_call.name, "args": function_call.args}
                for function_call in event.get_function_calls() or []
            )
        return {
            "status": "ok",
            "session_id": session_id,
            "final_response": final_response,
            "messages": messages,
            "function_calls": function_calls,
            "state": state,
        }

    async def _load_state(self, session_id: str) -> dict[str, Any]:
        session = await self.session_service.get_session(
            app_name="mobile_ax_tester_mcp",
            user_id=USER_ID,
            session_id=session_id,
        )
        return dict(session.state) if session else {}


def _mobile_test_request(state: dict[str, Any]) -> genai_types.Content:
    max_steps = state.get(str(MobileContextKey.MAX_STEPS), 50)
    max_activities = state.get(str(MobileContextKey.MAX_ACTIVITIES), 3)
    max_depth = state.get(str(MobileContextKey.MAX_DEPTH), 5)
    return genai_types.Content(
        role="user",
        parts=[
            genai_types.Part(
                text=(
                    "Run the mobile accessibility test now. "
                    f"Call run_mobile_test with max_steps={max_steps}, "
                    f"max_activities={max_activities}, max_depth={max_depth}."
                )
            )
        ],
    )


mobile_bridge = MobileAgentBridge()


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


def _build_mobile_scan_result(bridge_result: dict[str, Any]) -> mcp_types.CallToolResult:
    report_artifact = bridge_result.get("report_artifact")
    if not isinstance(report_artifact, dict) or not report_artifact.get("report_id"):
        return _error_result(
            "The accessibility test completed without a saved report artifact.",
            {
                "session_id": bridge_result.get("session_id"),
                "current_url": bridge_result.get("current_url"),
                "final_response": bridge_result.get("final_response", ""),
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
                "session_id": bridge_result.get("session_id"),
                "current_url": bridge_result.get("current_url"),
                "report_id": report_id,
                "report_artifact": report_artifact,
            },
        )

    return mcp_types.CallToolResult(
        content=content,
        structuredContent={
            "status": bridge_result.get("status", "ok"),
            "session_id": bridge_result.get("session_id"),
            "current_url": bridge_result.get("current_url"),
            "final_response": bridge_result.get("final_response", ""),
            "messages": bridge_result.get("messages", []),
            "function_calls": bridge_result.get("function_calls", []),
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
        bridge_result = await mobile_bridge.run_turn(
            {
                str(MobileContextKey.APP_PACKAGE): app_package,
                str(MobileContextKey.APP_ACTIVITY): app_activity,
                str(MobileContextKey.CAPABILITY_ID): capability_id,
                str(MobileContextKey.PLATFORM): platform,
                str(MobileContextKey.MAX_STEPS): max_steps,
                str(MobileContextKey.MAX_ACTIVITIES): max_activities,
                str(MobileContextKey.MAX_DEPTH): max_depth,
            }
        )
        bridge_result["report_artifact"] = run_save_mobile(bridge_result.get("state", {}))
        bridge_result["current_url"] = f"mobile://{app_package}/{app_activity}"
        return _build_mobile_scan_result(bridge_result)
    except Exception as exc:
        return _error_result(str(exc), {"capability_id": capability_id})


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
