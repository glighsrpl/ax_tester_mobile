"""Base interfaces shared by mobile accessibility testing tools."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from schemas import ScoreInfo
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
