from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

SeverityKey = Literal["critical", "serious", "moderate", "minor"]
SourceType = Literal[
    "axe-core",
    "llm",
    "both",
    "llm/image-analyzer",
    "llm/focus_visible_analyzer",
    "llm/link_purpose_analyzer",
    "llm/on_focus_analyzer",
    "llm/no_keyboard_trap",
]
ConfidenceLevel = Literal["high", "medium", "low"]
WcagRule = Literal[
    "1.1.1 - Non-text Content (Level A)",
    "1.2.1 - Audio-only and Video-only (Prerecorded) (Level A)",
    "1.2.2 - Captions (Prerecorded) (Level A)",
    "1.2.3 - Audio Description or Media Alternative (Prerecorded) (Level A)",
    "1.3.1 - Info and Relationships (Level A)",
    "1.3.2 - Meaningful Sequence (Level A)",
    "1.3.3 - Sensory Characteristics (Level A)",
    "1.4.1 - Use of Color (Level A)",
    "1.4.2 - Audio Control (Level A)",
    "2.1.1 - Keyboard (Level A)",
    "2.1.2 - No Keyboard Trap (Level A)",
    "2.2.1 - Timing Adjustable (Level A)",
    "2.2.2 - Pause, Stop, Hide (Level A)",
    "2.3.1 - Three Flashes or Below Threshold (Level A)",
    "2.4.1 - Bypass Blocks (Level A)",
    "2.4.2 - Page Titled (Level A)",
    "2.4.3 - Focus Order (Level A)",
    "2.4.4 - Link Purpose (In Context) (Level A)",
    "2.5.1 - Pointer Gestures (Level A)",
    "2.5.2 - Pointer Cancellation (Level A)",
    "2.5.3 - Label in Name (Level A)",
    "2.5.4 - Motion Actuation (Level A)",
    "3.1.1 - Language of Page (Level A)",
    "3.2.1 - On Focus (Level A)",
    "3.2.2 - On Input (Level A)",
    "3.3.1 - Error Identification (Level A)",
    "3.3.2 - Labels or Instructions (Level A)",
    "4.1.2 - Name, Role, Value (Level A)",
    "1.2.4 - Captions (Live) (Level AA)",
    "1.2.5 - Audio Description (Prerecorded) (Level AA)",
    "1.3.4 - Orientation (Level AA)",
    "1.3.5 - Identify Input Purpose (Level AA)",
    "1.4.3 - Contrast (Minimum) (Level AA)",
    "1.4.4 - Resize text (Level AA)",
    "1.4.5 - Images of Text (Level AA)",
    "1.4.10 - Reflow (Level AA)",
    "1.4.11 - Non-text Contrast (Level AA)",
    "1.4.12 - Text Spacing (Level AA)",
    "1.4.13 - Content on Hover or Focus (Level AA)",
    "2.4.5 - Multiple Ways (Level AA)",
    "2.4.6 - Headings and Labels (Level AA)",
    "2.4.7 - Focus Visible (Level AA)",
    "2.5.7 - Dragging Movements (Level AA)",
    "2.5.8 - Target Size (Minimum) (Level AA)",
    "3.1.2 - Language of Parts (Level AA)",
    "3.2.3 - Consistent Navigation (Level AA)",
    "3.2.4 - Consistent Identification (Level AA)",
    "3.3.3 - Error Suggestion (Level AA)",
    "3.3.4 - Error Prevention (Legal, Financial, Data) (Level AA)",
    "4.1.3 - Status Messages (Level AA)",
    "1.2.6 - Sign Language (Prerecorded) (Level AAA)",
    "1.2.7 - Extended Audio Description (Prerecorded) (Level AAA)",
    "1.2.8 - Media Alternative (Prerecorded) (Level AAA)",
    "1.2.9 - Audio-only (Live) (Level AAA)",
    "1.3.6 - Identify Purpose (Level AAA)",
    "1.4.6 - Contrast (Enhanced) (Level AAA)",
    "1.4.7 - Low or No Background Audio (Level AAA)",
    "1.4.8 - Visual Presentation (Level AAA)",
    "1.4.9 - Images of Text (No Exception) (Level AAA)",
    "2.1.3 - Keyboard (No Exception) (Level AAA)",
    "2.1.4 - Character Key Shortcuts (Level AAA)",
    "2.2.3 - No Timing (Level AAA)",
    "2.2.4 - Interruptions (Level AAA)",
    "2.2.5 - Re-authenticating (Level AAA)",
    "2.2.6 - Timeouts (Level AAA)",
    "2.3.2 - Three Flashes (Level AAA)",
    "2.4.8 - Location (Level AAA)",
    "2.4.9 - Link Purpose (Link Only) (Level AAA)",
    "2.4.10 - Section Headings (Level AAA)",
    "2.5.5 - Target Size (Level AAA)",
    "2.5.6 - Concurrent Input Mechanisms (Level AAA)",
    "3.1.3 - Unusual Words (Level AAA)",
    "3.1.4 - Abbreviations (Level AAA)",
    "3.1.5 - Reading Level (Level AAA)",
    "3.1.6 - Pronunciation (Level AAA)",
    "3.2.5 - Change on Request (Level AAA)",
    "3.3.5 - Help (Level AAA)",
    "3.3.6 - Error Prevention (All) (Level AAA)",
    "best-practice",
]


class PotentialExposure(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"additionalProperties": False})

    category: str = Field(...)
    description: str = Field(...)


class Issue(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"additionalProperties": False})

    id: str = Field(...)
    wcag_rule: WcagRule = Field(...)
    description: str = Field(...)
    severity: SeverityKey = Field(...)
    source: SourceType = Field(...)
    confidence: ConfidenceLevel = Field(...)
    html_snippet: str = Field(...)
    fix: str = Field(...)
    image_url_or_path: str | None = Field(...)
    why_this_matters: str = Field(...)
    potential_exposures: list[PotentialExposure] = Field(...)

    @model_validator(mode="before")
    @classmethod
    def _fill_legacy_qualitative_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            data.setdefault("why_this_matters", "")
            data.setdefault("potential_exposures", [])
            data.setdefault("image_url_or_path", None)
        return data


class IssueList(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"additionalProperties": False})

    issue_list: list[Issue] = Field(...)


class MetadataItem(BaseModel):
    model_config = ConfigDict(extra="forbid", json_schema_extra={"additionalProperties": False})

    key: str
    value: str | int


class ScoreInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "additionalProperties": False,
            "required": ["level_A", "level_AA", "level_AAA"],
        },
    )

    level_A: int = Field(0)
    level_AA: int = Field(0)
    level_AAA: int = Field(0)


class Report(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        json_schema_extra={
            "additionalProperties": False,
            "required": [
                "tool_name",
                "total_issues",
                "page",
                "issue_list",
                "score_passed",
                "score_total",
                "metadata",
            ],
        },
    )

    tool_name: str = Field(...)
    total_issues: int = Field(...)
    page: str = Field(...)
    issue_list: list[Issue] = Field(...)
    score_passed: ScoreInfo = Field(default_factory=ScoreInfo)
    score_total: ScoreInfo = Field(default_factory=ScoreInfo)
    metadata: list[MetadataItem] = Field(default_factory=list)
