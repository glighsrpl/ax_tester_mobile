"""Sanitization helpers for strings used in file paths, labels, and other contexts where special characters may be problematic."""


def sanitize_label(raw: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in raw).strip("._-")
