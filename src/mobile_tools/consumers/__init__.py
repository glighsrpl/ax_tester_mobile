from .base import MobileBaseConsumer
from .form_label import FormLabelConsumer
from .keyboard_accessibility import KeyboardAccessibilityConsumer
from .label_in_name import LabelInNameConsumer
from .name_role_value import NameRoleValueConsumer
from .non_text_content import NonTextContentConsumer
from .page_title import PageTitleConsumer
from .touch_target import TouchTargetConsumer


def build_default_mobile_consumers() -> list[MobileBaseConsumer]:
    return [
        NameRoleValueConsumer(),
        NonTextContentConsumer(),
        LabelInNameConsumer(),
        KeyboardAccessibilityConsumer(),
        TouchTargetConsumer(),
        FormLabelConsumer(),
        PageTitleConsumer(),
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
