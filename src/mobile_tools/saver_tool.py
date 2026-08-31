"""Save mobile accessibility test reports to disk and generate report artifacts."""

import json
from collections.abc import Mapping, MutableMapping
from datetime import datetime
from pathlib import Path
from typing import Any

from common import MobileContextKey
from schemas import ScoreInfo
from tools.saver_tool import _get_run_dir, _merge_score, _safe_int, _write_run_artifacts, generate_run_timestamp


def save_mobile_report(
    *,
    app_package: str,
    app_activity: str,
    capability_id: str,
    navigator_data: dict[str, Any],
    static_results: list[Any],
) -> dict[str, Any]:
    report_id = _report_id(navigator_data, app_package)
    report_dir = _get_run_dir(report_id)
    reports = _build_screen_reports(
        app_package, app_activity, capability_id, navigator_data, static_results, report_id
    )

    results_file = report_dir / "results.json"
    with open(results_file, "w", encoding="utf-8") as file:
        json.dump(reports, file, indent=2, ensure_ascii=False)

    report_artifact = _write_run_artifacts(report_id, report_dir, reports)
    debug_dir = _write_static_debug_artifacts(
        report_dir,
        static_debug_data=_state_debug_payload(static_results),
    )
    return {
        "status": "saved",
        "report_id": report_id,
        "run_dir": str(report_dir),
        "results_file": str(results_file),
        "debug_dir": str(debug_dir) if debug_dir else None,
        "report": reports,
        **report_artifact,
    }


def run_save_mobile(state: MutableMapping[Any, Any]) -> dict[str, Any]:
    navigator_data = _state_dict(state, MobileContextKey.NAVIGATOR_DATA)
    if not navigator_data:
        raise ValueError("Missing mobile navigator data.")
    static_results = _state_value(state, MobileContextKey.STATIC_RESULTS)
    if isinstance(static_results, Mapping) and isinstance(static_results.get("issue_list"), list):
        static_results = [{"result": static_results}]
    static_debug_data = _state_value(state, MobileContextKey.STATIC_DEBUG_DATA)

    report_artifact = save_mobile_report(
        app_package=_state_str(state, MobileContextKey.APP_PACKAGE),
        app_activity=_state_str(state, MobileContextKey.APP_ACTIVITY),
        capability_id=_state_str(state, MobileContextKey.CAPABILITY_ID),
        navigator_data=navigator_data,
        static_results=_with_static_debug(
            static_results if isinstance(static_results, list) else [],
            static_debug_data,
        ),
    )
    state[MobileContextKey.REPORT_ARTIFACT] = report_artifact
    state[str(MobileContextKey.REPORT_ARTIFACT)] = report_artifact
    return report_artifact


def _with_static_debug(static_results: list[Any], static_debug_data: Any) -> list[Any]:
    if not isinstance(static_debug_data, list):
        return static_results
    return [*static_results, {"debug": static_debug_data}]


def _state_debug_payload(static_results: list[Any]) -> list[dict[str, Any]]:
    for item in static_results:
        if isinstance(item, Mapping) and isinstance(item.get("debug"), list):
            return [debug for debug in item["debug"] if isinstance(debug, dict)]
    return []


def _write_static_debug_artifacts(report_dir: Path, static_debug_data: list[dict[str, Any]]) -> Path | None:
    if not static_debug_data:
        return None
    debug_dir = report_dir / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    debug_dir.mkdir(parents=True, exist_ok=True)
    for index, debug_payload in enumerate(static_debug_data, start=1):
        debug_file = debug_dir / f"static_input_{index:04d}.json"
        with open(debug_file, "w", encoding="utf-8") as file:
            json.dump(debug_payload, file, indent=2, ensure_ascii=False, default=str)
    return debug_dir


def _build_screen_reports(
    app_package: str,
    app_activity: str,
    capability_id: str,
    navigator_data: dict[str, Any],
    static_results: list[Any],
    report_id: str,
) -> list[dict[str, Any]]:
    activities = _visited_activities(navigator_data, app_activity)
    issues_by_activity: dict[str, list[dict[str, Any]]] = {activity: [] for activity in activities}
    score_passed = ScoreInfo()
    score_total = ScoreInfo()
    checked = 0

    for consumer in static_results:
        result = consumer.get("result", {}) if isinstance(consumer, Mapping) else {}
        activity_issues = result.get("issues_by_activity", {}) if isinstance(result, Mapping) else {}
        if isinstance(activity_issues, Mapping) and "issues_by_activity" in result:
            _append_activity_issues(issues_by_activity, activities, activity_issues)
            issue_list = []
        else:
            issue_list = result.get("issue_list", []) if isinstance(result, Mapping) else []
        if isinstance(issue_list, list):
            for issue in issue_list:
                if not isinstance(issue, dict):
                    continue
                activity = str(issue.get("activity") or app_activity or "unknown").strip()
                if activity not in issues_by_activity:
                    activities.append(activity)
                    issues_by_activity[activity] = []
                issues_by_activity[activity].append(_with_activity(issue, activity))
        checked += _safe_int(result.get("checked", 0)) if isinstance(result, Mapping) else 0
        _merge_score(score_passed, result.get("score_passed", {}) if isinstance(result, Mapping) else {})
        _merge_score(score_total, result.get("score_total", {}) if isinstance(result, Mapping) else {})

    return [
        _build_screen_report(
            app_package=app_package,
            app_activity=app_activity,
            capability_id=capability_id,
            navigator_data=navigator_data,
            report_id=report_id,
            activity=activity,
            issues=issues_by_activity.get(activity, []),
            checked=checked,
            score_passed=score_passed,
            score_total=score_total,
        )
        for activity in activities
    ]


def _append_activity_issues(
    issues_by_activity: dict[str, list[dict[str, Any]]],
    activities: list[str],
    activity_issues: Mapping[Any, Any],
) -> None:
    for raw_activity, raw_issues in activity_issues.items():
        activity = str(raw_activity).strip() or "unknown"
        if activity not in issues_by_activity:
            activities.append(activity)
            issues_by_activity[activity] = []
        if not isinstance(raw_issues, list):
            continue
        issues_by_activity[activity].extend(
            _with_activity(issue, activity) for issue in raw_issues if isinstance(issue, dict)
        )


def _build_screen_report(
    *,
    app_package: str,
    app_activity: str,
    capability_id: str,
    navigator_data: dict[str, Any],
    report_id: str,
    activity: str,
    issues: list[dict[str, Any]],
    checked: int,
    score_passed: ScoreInfo,
    score_total: ScoreInfo,
) -> dict[str, Any]:
    activity_screenshot_paths = navigator_data.get("activity_screenshots", {})
    screenshot_path = (
        activity_screenshot_paths.get(activity) if isinstance(activity_screenshot_paths, Mapping) else None
    )
    if screenshot_path is None and activity == (app_activity or "unknown"):
        screenshot_path = navigator_data.get("page_screenshot")

    return {
        "tool_name": "mobile_ax_tester",
        "total_issues": len(issues),
        "page": _mobile_page(app_package, activity),
        "page_screenshot": screenshot_path,
        "date_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "issue_list": issues,
        "score_passed": score_passed.model_dump(),
        "score_total": score_total.model_dump(),
        "metadata": [
            {"key": "report_id", "value": report_id},
            {"key": "app_package", "value": app_package},
            {"key": "app_activity", "value": app_activity},
            {"key": "capability_id", "value": capability_id},
            {"key": "steps", "value": _safe_int(navigator_data.get("steps", 0))},
            {"key": "checked", "value": checked},
        ],
    }


def _with_activity(issue: dict[str, Any], activity: str) -> dict[str, Any]:
    enriched = issue.copy()
    enriched["activity"] = activity.strip() or "unknown"
    return enriched


def _mobile_page(app_package: str, activity: str) -> str:
    return f"mobile://{app_package}/{activity}"


def _report_id(navigator_data: Mapping[str, Any], app_package: str) -> str:
    configured_report_id = navigator_data.get("report_id")
    if isinstance(configured_report_id, str) and configured_report_id.strip():
        return configured_report_id.strip()
    return f"{generate_run_timestamp()}_{_label(app_package)}"


def _label(value: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in value).strip("._-") or "mobile"


def _state_value(state: Mapping[Any, Any], key: object) -> Any:
    return state.get(key) or state.get(str(key))


def _state_str(state: Mapping[Any, Any], key: object) -> str:
    return str(_state_value(state, key) or "").strip()


def _state_dict(state: Mapping[Any, Any], key: object) -> dict[str, Any]:
    value = _state_value(state, key)
    return value if isinstance(value, dict) else {}


def _visited_activities(navigator_data: Mapping[str, Any], default: str) -> list[str]:
    activities = navigator_data.get("visited_activities")
    if isinstance(activities, list):
        values = [activity for activity in (str(value).strip() for value in activities) if activity]
        if values:
            return list(dict.fromkeys(values))
    return [default or "unknown"]
