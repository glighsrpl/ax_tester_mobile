"""Base interfaces shared by mobile accessibility testing tools."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from schemas import ScoreInfo

_IN_PLACE_CONTROL_CLASS_NAMES = (
    "checkbox",
    "switch",
    "togglebutton",
    "radiobutton",
    "seekbar",
    "compoundbutton",
    "ratingbar",
)


class ToolStatus(StrEnum):
    """Execution status of a tool"""

    SUCCESS = "success"
    FAILURE = "failure"
    TIMEOUT = "timeout"
    SKIPPED = "skipped"


@dataclass
class ToolResult:
    """Standardized result format for all tools

    Attributes:
        tool_name: Name of the tool that generated this result
        status: Execution status
        data: Tool-specific result data
        error: Error message if status is FAILURE
        metadata: Additional metadata (e.g., URL, timestamp)

    """

    tool_name: str
    status: ToolStatus
    data: dict[str, Any]
    score_passed: ScoreInfo = field(default_factory=ScoreInfo)
    score_total: ScoreInfo = field(default_factory=ScoreInfo)
    error: str | None = None
    metadata: dict[str, Any] | None = None

    def is_success(self) -> bool:
        """Check if execution was successful"""
        return self.status == ToolStatus.SUCCESS

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization"""
        score_passed = self.score_passed.model_dump()
        score_total = self.score_total.model_dump()
        return {
            "tool_name": self.tool_name,
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "score_passed": score_passed,
            "score_total": score_total,
            "metadata": self.metadata or {},
        }


class Tool(ABC):
    """Abstract base class for mobile accessibility testing tools."""

    def __init__(self, config: dict[str, Any] | None = None):
        self.config = config or {}
        self.name = self.__class__.__name__

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the accessibility test."""
        raise NotImplementedError

    def __str__(self) -> str:
        return f"{self.name}(config={self.config})"


@dataclass
class MobileElementInfo:
    """Accessibility attributes extracted from one mobile UI element."""

    index: int
    text: str | None = None
    content_desc: str | None = None
    resource_id: str | None = None
    class_name: str | None = None
    package: str | None = None
    bounds: str | None = None
    clickable: bool = False
    focusable: bool = False
    enabled: bool = True
    selected: bool = False
    checked: bool | None = None
    expanded: bool | None = None
    page_screenshot: str | None = None
    element_screenshot: str | None = None
    focused: bool = False
    hint: str | None = None
    label_for: str | None = None
    input_type: str | None = None
    parent_index: int | None = None
    important_for_accessibility: str | None = None
    font_size: float | None = None
    font_style: str | None = None

    def get_label(self) -> str:
        return self.content_desc or self.text or self.resource_id or ""

    def get_focus_key(self) -> str:
        return f"idx:{self.index}:bounds:{self.bounds or ''}"

    def is_interactive(self) -> bool:
        return self.clickable or self.focusable


def is_in_place_control(element: MobileElementInfo) -> bool:
    """Return whether an element updates in place instead of opening a screen."""
    class_name = (element.class_name or "").casefold()
    return any(name in class_name for name in _IN_PLACE_CONTROL_CLASS_NAMES)


@dataclass
class MobileKeyboardResult:
    """Keyboard traversal elements and detected focus traps for one screen."""

    reachable: list[MobileElementInfo]
    unreachable: list[MobileElementInfo]
    focus_order: list[MobileElementInfo]
    traps: list[dict]
    activity: str
