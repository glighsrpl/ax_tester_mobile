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


class MobileContextKey(StrEnum):
    # inputs
    APP_PACKAGE = "mobile_app_package"
    APP_ACTIVITY = "mobile_app_activity"
    CAPABILITY_ID = "mobile_capability_id"
    MAX_STEPS = "mobile_max_steps"
    MAX_ACTIVITIES = "mobile_max_activities"
    MAX_DEPTH = "mobile_max_depth"
    INSTRUCTIONS = "mobile_instructions"

    # outcomes
    NAVIGATOR_DATA = "mobile_navigator_data"
    STATIC_RESULTS = "mobile_static_results"
    STATIC_DEBUG_DATA = "mobile_static_debug_data"
    DETERMINISTIC_REPORT = "mobile_deterministic_report"
    CONTRAST_REPORT = "mobile_contrast_report"
    LLM_REPORT = "mobile_llm_report"

    # saved artifacts
    REPORT_ARTIFACT = "mobile_report_artifact"


FINAL_REPORT_KEYS: tuple[ContextKey, ...] = (
    ContextKey.STATIC_REPORT,
    ContextKey.IMAGE_ANALYZER_REPORT,
    ContextKey.FOCUS_VISIBLE_REPORT,
    ContextKey.LINK_PURPOSE_REPORT,
    ContextKey.ON_FOCUS_REPORT,
    ContextKey.NO_KEYBOARD_TRAP_REPORT,
)
