import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any

from schemas import ScoreInfo
from tools.saver_tool import _get_run_dir, _merge_score, _safe_int, _write_run_artifacts, generate_run_timestamp


def save_mobile_report(
    *,
    app_package: str,
    app_activity: str,
    capability_id: str,
    navigator_data: dict[str, Any],
) -> dict[str, Any]:
    report_id = f"{generate_run_timestamp()}_{_label(app_package)}"
    report_dir = _get_run_dir(report_id)
    reports = _build_screen_reports(app_package, app_activity, capability_id, navigator_data, report_id)

    results_file = report_dir / "results.json"
    with open(results_file, "w", encoding="utf-8") as file:
        json.dump(reports, file, indent=2, ensure_ascii=False)

    report_artifact = _write_run_artifacts(report_id, report_dir, reports)
    return {
        "status": "saved",
        "report_id": report_id,
        "run_dir": str(report_dir),
        "results_file": str(results_file),
        "report": reports,
        **report_artifact,
    }


def _build_screen_reports(
    app_package: str,
    app_activity: str,
    capability_id: str,
    navigator_data: dict[str, Any],
    report_id: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    score_passed = ScoreInfo()
    score_total = ScoreInfo()
    checked = 0

    for consumer in navigator_data.get("consumer_results", []) or []:
        result = consumer.get("result", {}) if isinstance(consumer, Mapping) else {}
        issue_list = result.get("issue_list", []) if isinstance(result, Mapping) else []
        if isinstance(issue_list, list):
            issues.extend(_with_screen_id(issue) for issue in issue_list if isinstance(issue, dict))
        checked += _safe_int(result.get("checked", 0)) if isinstance(result, Mapping) else 0
        _merge_score(score_passed, result.get("score_passed", {}) if isinstance(result, Mapping) else {})
        _merge_score(score_total, result.get("score_total", {}) if isinstance(result, Mapping) else {})

    issues_by_screen: dict[str, list[dict[str, Any]]] = {}
    for issue in issues:
        screen_id = str(issue.get("screen_id") or "unknown").strip() or "unknown"
        issues_by_screen.setdefault(screen_id, []).append(issue)

    screen_ids = [
        str(screen_id).strip()
        for screen_id in navigator_data.get("visited_screens", []) or []
        if str(screen_id).strip()
    ]
    for screen_id in issues_by_screen:
        if screen_id not in screen_ids:
            screen_ids.append(screen_id)
    if not screen_ids:
        screen_ids.append("unknown")

    return [
        _build_screen_report(
            app_package=app_package,
            app_activity=app_activity,
            capability_id=capability_id,
            navigator_data=navigator_data,
            report_id=report_id,
            screen_id=screen_id,
            screen_index=index,
            issues=issues_by_screen.get(screen_id, []),
            checked=checked,
            score_passed=score_passed,
            score_total=score_total,
        )
        for index, screen_id in enumerate(screen_ids, start=1)
    ]


def _build_screen_report(
    *,
    app_package: str,
    app_activity: str,
    capability_id: str,
    navigator_data: dict[str, Any],
    report_id: str,
    screen_id: str,
    screen_index: int,
    issues: list[dict[str, Any]],
    checked: int,
    score_passed: ScoreInfo,
    score_total: ScoreInfo,
) -> dict[str, Any]:
    return {
        "tool_name": "mobile_ax_tester",
        "total_issues": len(issues),
        "page": _mobile_page(app_package, app_activity, screen_id),
        "screen_id": screen_id,
        "page_screenshot": navigator_data.get("page_screenshot") if screen_index == 1 else None,
        "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "issue_list": issues,
        "score_passed": score_passed.model_dump(),
        "score_total": score_total.model_dump(),
        "metadata": [
            {"key": "report_id", "value": report_id},
            {"key": "app_package", "value": app_package},
            {"key": "app_activity", "value": app_activity},
            {"key": "capability_id", "value": capability_id},
            {"key": "screen_id", "value": screen_id},
            {"key": "screen_index", "value": screen_index},
            {"key": "screens", "value": len(navigator_data.get("visited_screens", []) or [])},
            {"key": "steps", "value": _safe_int(navigator_data.get("steps", 0))},
            {"key": "checked", "value": checked},
        ],
    }


def _with_screen_id(issue: dict[str, Any]) -> dict[str, Any]:
    enriched = issue.copy()
    enriched["screen_id"] = str(
        enriched.get("screen_id") or _screen_id_from_issue_id(enriched.get("id"))
    ).strip()
    return enriched


def _screen_id_from_issue_id(issue_id: Any) -> str:
    parts = str(issue_id or "").rsplit("-", 2)
    return parts[-2] if len(parts) == 3 and parts[-2] else "unknown"


def _mobile_page(app_package: str, app_activity: str, screen_id: str) -> str:
    return f"mobile://{app_package}/{app_activity}#screen_id={screen_id}"


def _label(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-") or "mobile"
