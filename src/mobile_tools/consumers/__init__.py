from .base import MobileBaseConsumer
from .form_label import FormLabelConsumer
from .keyboard_accessibility import KeyboardAccessibilityConsumer
from .label_in_name import LabelInNameConsumer
from .name_role_value import NameRoleValueConsumer
from .page_title import PageTitleConsumer
from .touch_target import TouchTargetConsumer


def build_default_mobile_consumers() -> list[MobileBaseConsumer]:
    """Build a list of default mobile consumers for deterministic accessibility analysis."""
    return [
        NameRoleValueConsumer(), # deterministic check for WCAG 1.3.1 Info and Relationships

        KeyboardAccessibilityConsumer(), # deterministic check for WCAG 2.1.1 Keyboard
        PageTitleConsumer(), # check for WCAG 2.4.2 Page Title
        LabelInNameConsumer(), # deterministic check for WCAG 2.5.3 Label in Name
        TouchTargetConsumer(), # deterministic check for WCAG 2.5.8 Target Size

        FormLabelConsumer(), # check for WCAG 3.3.2 Labels or Instructions
    ]


__all__ = [
    "MobileBaseConsumer",
    "FormLabelConsumer",
    "KeyboardAccessibilityConsumer",
    "LabelInNameConsumer",
    "NameRoleValueConsumer",
    "NonTextContentConsumer",
    "PageTitleConsumer",
    "TouchTargetConsumer",
    "build_default_mobile_consumers",
]
