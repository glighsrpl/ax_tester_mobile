"""Deterministic MCP service for touch-based mobile accessibility scans."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from tools.mobile_saver_tool import generate_run_timestamp
from tools.mobile_screen_scanner import MobileScreenNavigator
from utils.helpers import sanitize_label
from utils.mobile_pipeline import (
    ActivityReports,
    MobileStaticAnalyzer,
    StaticAnalysisResult,
    run_mobile_pipeline,
)
from utils.mobile_report import save_source_reports
from utils.mobile_session import MobileSession, mobile_session
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
        initial_tree_xml = await _require_accessibility_tree(session, request.capability_id)
        return await _run_scan_pipeline(request, initial_tree_xml)


async def _require_accessibility_tree(session: MobileSession, capability_id: str) -> str:
    page_source = await session.get_accessibility_tree()
    if page_source and len(page_source) >= 100:
        return page_source
    serial = capability_id.removeprefix("local-android:")
    raise RuntimeError(f"Empty UI tree from device {serial}, session may not be ready")


async def _run_scan_pipeline(
    request: MobileAccessibilityScanRequest,
    initial_tree_xml: str,
) -> MobileAccessibilityScanResult:
    report_id = f"{generate_run_timestamp()}_{sanitize_label(request.app_package) or 'mobile'}"
    navigator = MobileScreenNavigator(
        {
            "max_steps": request.max_steps,
            "max_activities": request.max_activities,
            "max_depth": request.max_depth,
            "target_app_package": request.app_package,
            "initial_tree_xml": initial_tree_xml,
            "run_id": report_id,
            "screenshot_output_dir": str(REPORTS_ROOT / report_id / "screenshots"),
        }
    )
    navigator_data, static_analysis = await run_mobile_pipeline(
        navigator,
        MobileStaticAnalyzer(request.platform),
        MAX_CONCURRENT_STATIC_ANALYSES,
    )
    return _build_scan_result(report_id, navigator_data, static_analysis)


def _build_scan_result(
    report_id: str,
    navigator_data: dict[str, object],
    static_analysis: StaticAnalysisResult,
) -> MobileAccessibilityScanResult:
    navigator_data["report_id"] = report_id
    _save_activity_reports(REPORTS_ROOT / report_id / "static_reports", static_analysis.activity_reports)
    static_results = static_analysis.report.model_dump(mode="json")
    static_results["issues_by_activity"] = {
        activity: [issue.model_dump(mode="json") for issue in issues]
        for activity, issues in static_analysis.issues_by_activity.items()
    }
    return MobileAccessibilityScanResult(
        navigator_data=navigator_data,
        static_results=static_results,
        static_debug_data=static_analysis.debug_data,
        activities=_activity_count(navigator_data),
    )


def _activity_count(data: dict[str, object]) -> int:
    activities = data.get("visited_activities")
    return len(activities) if isinstance(activities, list) else 0


def _save_activity_reports(
    report_dir: Path,
    activity_reports: Mapping[str, ActivityReports],
) -> None:
    multiple_activities = len(activity_reports) > 1
    for activity, reports in activity_reports.items():
        directory = report_dir / (sanitize_label(activity) or "mobile") if multiple_activities else report_dir
        save_source_reports(
            directory,
            reports.deterministic,
            reports.contrast,
            reports.llm,
            cross_screen=reports.cross_screen,
            merge=reports.merge,
        )
