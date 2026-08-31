from enum import StrEnum


class MobileContextKey(StrEnum):
    # inputs
    APP_PACKAGE = "mobile_app_package"
    APP_ACTIVITY = "mobile_app_activity"
    CAPABILITY_ID = "mobile_capability_id"
    PLATFORM = "mobile_platform"
    MAX_STEPS = "mobile_max_steps"
    MAX_ACTIVITIES = "mobile_max_activities"
    MAX_DEPTH = "mobile_max_depth"
    INSTRUCTIONS = "mobile_instructions"

    # final outcomes
    NAVIGATOR_DATA = "mobile_navigator_data"
    STATIC_RESULTS = "mobile_static_results"
    STATIC_DEBUG_DATA = "mobile_static_debug_data"
    DETERMINISTIC_ISSUES = "mobile_deterministic_issues"
    DETERMINISTIC_REPORT = "mobile_deterministic_report"
    CONTRAST_REPORT = "mobile_contrast_report"
    LLM_REPORT = "mobile_llm_report"

    # saved artifacts
    REPORT_ARTIFACT = "mobile_report_artifact"
