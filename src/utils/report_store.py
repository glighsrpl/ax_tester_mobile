from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, NamedTuple

REPORTS_ROOT = Path(__file__).resolve().parents[2] / "results"
REPORT_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2}(?:_[A-Za-z0-9][A-Za-z0-9._-]*)?$")


class ReportFileSpec(NamedTuple):
    file_type: str
    filename: str
    mime_type: str
    is_binary: bool


REPORT_FILE_SPECS: dict[str, ReportFileSpec] = {
    "json": ReportFileSpec("json", "ax_report.json", "application/json", False),
    "powerpoint": ReportFileSpec(
        "powerpoint",
        "ax_report.pptx",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        True,
    ),
    "excel": ReportFileSpec(
        "excel",
        "ax_report.xlsx",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        True,
    ),
}


def _validate_report_id(report_id: str) -> str:
    if not isinstance(report_id, str) or not REPORT_ID_PATTERN.fullmatch(report_id):
        raise ValueError(
            "Invalid report_id. Expected timestamp format YYYY-MM-DD_HH-MM-SS "
            "with an optional sanitized host suffix."
        )
    return report_id


def get_report_file_spec(file_type: str) -> ReportFileSpec:
    """Return metadata for a supported report file type."""
    if file_type in REPORT_FILE_SPECS:
        return REPORT_FILE_SPECS[file_type]
    raise ValueError(f"Unsupported file_type {file_type!r}. Supported values: {', '.join(REPORT_FILE_SPECS)}.")


def _get_report_dir(report_id: str) -> Path:
    report_id = _validate_report_id(report_id)
    report_dir = (REPORTS_ROOT / report_id).resolve()

    if report_dir.parent != REPORTS_ROOT.resolve():
        raise ValueError("Resolved report path is outside the reports directory.")

    return report_dir


def create_report_directory(report_id: str) -> tuple[str, Path]:
    """Create and return the directory for a report run."""
    report_id = _validate_report_id(report_id)
    report_dir = _get_report_dir(report_id)
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_id, report_dir


def _build_file_metadata(report_id: str, file_type: str, report_dir: Path | None = None) -> dict[str, Any]:
    spec = get_report_file_spec(file_type)
    report_dir = report_dir or _get_report_dir(report_id)
    file_path = report_dir / spec.filename

    return {
        "file_type": spec.file_type,
        "filename": spec.filename,
        "mime_type": spec.mime_type,
        "uri": f"ax-tester-mobile://reports/{_validate_report_id(report_id)}/{spec.filename}",
        "size_bytes": file_path.stat().st_size if file_path.exists() else None,
    }


def build_report_manifest(report_id: str, report_dir: Path | None = None) -> dict[str, Any]:
    """Build in-memory metadata for report files that exist."""
    report_id = _validate_report_id(report_id)
    report_dir = report_dir or _get_report_dir(report_id)

    files = [
        _build_file_metadata(report_id, file_type, report_dir)
        for file_type, spec in REPORT_FILE_SPECS.items()
        if (report_dir / spec.filename).exists()
    ]

    return {
        "report_id": report_id,
        "available_file_types": [file["file_type"] for file in files],
        "files": files,
    }


def get_report_file_metadata(report_id: str, file_type: str) -> dict[str, Any]:
    """Return report file metadata without reading file content."""
    file_path, _ = _resolve_report_file(report_id, file_type)
    return _build_file_metadata(report_id, file_type, file_path.parent)


def _resolve_report_file(report_id: str, file_type: str) -> tuple[Path, ReportFileSpec]:
    report_dir = _get_report_dir(report_id)
    spec = get_report_file_spec(file_type)

    if not report_dir.is_dir():
        raise FileNotFoundError(f"Report {report_id!r} was not found.")

    file_path = (report_dir / spec.filename).resolve()
    if file_path.parent != report_dir:
        raise ValueError("Resolved report file path is outside the report directory.")

    if not file_path.is_file():
        raise FileNotFoundError(f"Report file {spec.filename!r} was not found for report {report_id!r}.")

    return file_path, spec


def read_report_file(report_id: str, file_type: str) -> tuple[bytes, dict[str, Any]]:
    """Read a report file and return its bytes plus metadata."""
    file_path, _ = _resolve_report_file(report_id, file_type)
    metadata = _build_file_metadata(report_id, file_type, file_path.parent)
    return file_path.read_bytes(), metadata


def read_report_json(report_id: str) -> dict[str, Any]:
    """Read the JSON report as a dictionary."""
    content, _ = read_report_file(report_id, "json")
    report = json.loads(content.decode("utf-8"))

    if not isinstance(report, (dict, list)):
        raise ValueError(f"Invalid JSON report format for {report_id!r}.")

    return report
