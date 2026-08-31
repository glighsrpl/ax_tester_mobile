from enum import StrEnum


class ContextKey(StrEnum):
    # utils
    DOM_HTML = "dom_html"
    WCAG_PROMPT = "wcag_prompt"
    COMPLIANCE_LEVEL = "compliance_level"
    CRAWL_FOLDER_NAME = "crawl_folder_name"
    PAGE_SCREENSHOT = "page_screenshot"

    # temp storage
    LOOP_REPORT = "loop_report"
    LOOP_NOTES = "loop_notes"
    LOOP_ITERATION = "loop_iteration"
    AXE_REPORT = "axe_report"

    # final outcomes
    STATIC_REPORT = "static_report"
    IMAGE_ANALYZER_REPORT = "image_analyzer_report"
    FOCUS_VISIBLE_REPORT = "focus_visible_report"
    LINK_PURPOSE_REPORT = "link_purpose_report"
    ON_FOCUS_REPORT = "on_focus_report"
    NO_KEYBOARD_TRAP_REPORT = "no_keyboard_trap_report"

    # saved artifacts
    REPORT_ARTIFACT = "report_artifact"


FINAL_REPORT_KEYS: tuple[ContextKey, ...] = (
    ContextKey.STATIC_REPORT,
    ContextKey.IMAGE_ANALYZER_REPORT,
    ContextKey.FOCUS_VISIBLE_REPORT,
    ContextKey.LINK_PURPOSE_REPORT,
    ContextKey.ON_FOCUS_REPORT,
    ContextKey.NO_KEYBOARD_TRAP_REPORT,
)
