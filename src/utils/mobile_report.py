import json
from collections.abc import Iterable
from pathlib import Path

from mobile_agents.static_agent.deterministic_consumers import run_deterministic_analysis
from schemas import Issue, Report, ScoreInfo
from tools.mobile_screen_scanner import MobileScanSnapshot


def deterministic_report(snapshot: MobileScanSnapshot) -> Report:
    issues = run_deterministic_analysis(snapshot)
    return Report(
        tool_name="deterministic",
        total_issues=len(issues),
        page=f"mobile://{snapshot.activity}",
        issue_list=issues,
        metadata=[{"key": "snapshot_id", "value": snapshot.snapshot_id}],
    )


def save_source_reports(report_dir: Path, deterministic: Report, contrast: Report, llm: Report) -> None:
    report_dir.mkdir(parents=True, exist_ok=True)
    _write_report(report_dir / "deterministic.json", deterministic)
    _write_report(report_dir / "contrast_agent.json", contrast)
    _write_report(report_dir / "llm.json", llm)


def merge_static_reports(
    reports: list[Report],
    total_snapshots: int,
    issues_by_activity: dict[str, list[Issue]] | None = None,
    tool_name: str = "llm",
) -> Report:
    activity_issues = issues_by_activity or {
        "unknown": dedupe_issues(issue for report in reports for issue in report.issue_list)
    }
    issues = flatten_issues_by_activity(activity_issues)
    return Report(
        tool_name=tool_name,
        total_issues=len(issues),
        page="mobile",
        issue_list=issues,
        score_passed=_sum_scores(report.score_passed for report in reports),
        score_total=_sum_scores(report.score_total for report in reports),
        metadata=[{"key": "snapshots", "value": total_snapshots}],
    )


def flatten_issues_by_activity(issues_by_activity: dict[str, list[Issue]]) -> list[Issue]:
    """Return the legacy flat issue list without changing activity buckets."""
    return [issue for activity_issues in issues_by_activity.values() for issue in activity_issues]


def dedupe_issues(issues: Iterable[Issue]) -> list[Issue]:
    deduped: dict[tuple[str, str, str], Issue] = {}
    for issue in issues:
        deduped.setdefault((issue.wcag_rule, issue.html_snippet, issue.description), issue)
    return list(deduped.values())


def _write_report(path: Path, report: Report) -> None:
    path.write_text(json.dumps(report.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8")


def _sum_scores(scores: Iterable[ScoreInfo]) -> ScoreInfo:
    total = ScoreInfo()
    for score in scores:
        total.level_A += score.level_A
        total.level_AA += score.level_AA
        total.level_AAA += score.level_AAA
    return total
