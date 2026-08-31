"""Base interface for all accessibility testing tools"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from schemas import ScoreInfo
from utils.browser_session import NavigationCommand


@dataclass
class ActiveElementInfo:
    backend_dom_node_id: int | None
    page_screenshot: str | None
    element_screenshot: str | None
    element_ax_info: dict[str, Any] | None
    element_out_html: str | None
    element_html_tag: str | None
    element_href: str | None
    page_url: str | None
    page_title: str | None
    context_page_count: int | None

    def get_focus_key(self) -> str:
        if self.backend_dom_node_id is not None:
            return f"url:{self.page_url}:id:{self.backend_dom_node_id}"
        return f"url:{self.page_url}:html:{self.element_html_tag}:{self.element_out_html}"


@dataclass
class NavigatorState:
    """Navigation state snapshot around the current focus.

    Stores page/element screenshots and AX info for previous/current/next
    focus targets. Screenshots are typically base64-encoded strings.
    """

    path: list[NavigationCommand]

    # element info
    root_element: ActiveElementInfo | None
    prv_active_element: ActiveElementInfo | None
    cur_active_element: ActiveElementInfo | None


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
    """Abstract base class for all accessibility testing tools

    All tools must implement the execute method and follow
    the standardized ToolResult format.
    """

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize tool with optional configuration

        Args:
            config: Tool-specific configuration dictionary

        """
        self.config = config or {}
        self.name = self.__class__.__name__

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the accessibility test

        Args:
            **kwargs: Tool-specific parameters

        Returns:
            ToolResult with standardized format

        Raises:
            ToolExecutionError: If execution fails

        """
        pass

    def validate_url(self, url: str) -> str:
        """Validate and normalize URL

        Args:
            url: URL to validate

        Returns:
            Normalized URL

        Raises:
            ValueError: If URL is invalid

        """
        from urllib.parse import urlparse

        if not url:
            raise ValueError("URL cannot be empty")

        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL format: {url}")

        return url

    def __str__(self) -> str:
        return f"{self.name}(config={self.config})"


class ToolExecutionError(Exception):
    """Base exception for tool execution failures"""

    pass
