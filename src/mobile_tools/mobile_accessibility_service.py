"""Deterministic MCP service for touch-based mobile accessibility scans."""

from dataclasses import dataclass
from typing import Any

from mobile_tools.screen_scanner import MobileScreenScannerTool
from mobile_tools.saver_tool import generate_run_timestamp
from mobile_tools.utils.mobile_pipeline import (
    MobileStaticAnalyzer,
    run_mobile_pipeline,
)
from mobile_tools.utils.report_utils import save_source_reports
from mobile_tools.utils.session import MobileSession, mobile_session
from utils.report_store import REPORTS_ROOT

MAX_CONCURRENT_STATIC_ANALYSES = 4


@dataclass(frozen=True)
class MobileAccessibilityScanRequest:
    """Configuration required to collect and analyze touch-navigation snapshots."""

    app_package: str
    app_activity: str
    capability_id: str
    platform: str
    max_steps: int
    max_activities: int
    max_depth: int

    def normalized(self) -> "MobileAccessibilityScanRequest":
        """Return request values constrained to valid navigation limits."""
        if not self.app_package or not self.app_activity or not self.capability_id:
            raise ValueError("Missing mobile app package, activity, or capability id.")
        if self.platform not in {"Android", "iOS"}:
            raise ValueError(f"Unsupported mobile platform: {self.platform or 'unknown'}.")
        return MobileAccessibilityScanRequest(
            app_package=self.app_package,
            app_activity=self.app_activity,
            capability_id=self.capability_id,
            platform=self.platform,
            max_steps=max(int(self.max_steps), 1),
            max_activities=max(int(self.max_activities), 1),
            max_depth=max(int(self.max_depth), 0),
        )


@dataclass(frozen=True)
class MobileAccessibilityScanResult:
    """Artifacts produced by one touch-navigation accessibility scan."""

    report_id: str
    navigator_data: dict[str, object]
    static_results: dict[str, object]
    static_debug_data: list[dict[str, object]]
    activities: int


async def run_mobile_accessibility_scan(
    request: MobileAccessibilityScanRequest,
) -> MobileAccessibilityScanResult:
    """Run the complete touch-navigation and static-analysis flow in one session."""
    request = request.normalized()
    async with mobile_session(
        request.capability_id,
        request.app_package,
        request.app_activity,
    ) as session:
        await _require_accessibility_tree(session, request.capability_id)
        return await _collect_and_analyze(request)


async def _require_accessibility_tree(session: MobileSession, capability_id: str) -> None:
    page_source = await session.get_accessibility_tree()
    if page_source and len(page_source) >= 100:
        return
    serial = capability_id.removeprefix("local-android:")
    raise RuntimeError(f"Empty UI tree from device {serial}, session may not be ready")


async def _collect_and_analyze(
    request: MobileAccessibilityScanRequest,
) -> MobileAccessibilityScanResult:
    report_id = f"{generate_run_timestamp()}_{_report_label(request.app_package)}"
    navigator = MobileScreenScannerTool(
        {
            "max_steps": request.max_steps,
            "max_activities": request.max_activities,
            "max_depth": request.max_depth,
            "target_app_package": request.app_package,
            "run_id": report_id,
            "screenshot_output_dir": str(REPORTS_ROOT / report_id / "screenshots"),
        }
    )
    navigator_data, static_analysis = await run_mobile_pipeline(
        navigator,
        MobileStaticAnalyzer(request.platform),
        MAX_CONCURRENT_STATIC_ANALYSES,
    )
    navigator_data["report_id"] = report_id
    save_source_reports(
        REPORTS_ROOT / report_id / "static_reports",
        static_analysis.deterministic_report,
        static_analysis.contrast_report,
        static_analysis.llm_report,
    )
    static_results = static_analysis.report.model_dump(mode="json")
    static_results["issues_by_activity"] = {
        activity: [issue.model_dump(mode="json") for issue in issues]
        for activity, issues in static_analysis.issues_by_activity.items()
    }
    return MobileAccessibilityScanResult(
        report_id=report_id,
        navigator_data=navigator_data,
        static_results=static_results,
        static_debug_data=static_analysis.debug_data,
        activities=_activity_count(navigator_data),
    )


def _activity_count(data: dict[str, object]) -> int:
    activities = data.get("visited_activities")
    return len(activities) if isinstance(activities, list) else 0


def _report_label(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-") or "mobile"
