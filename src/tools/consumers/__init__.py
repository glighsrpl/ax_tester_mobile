from .base import BaseConsumer
from .focus_visible_consumer import FocusVisibleConsumer
from .link_purpose_consumer import LinkPurposeConsumer
from .no_keyboard_trap import NoKeyboardTrapConsumer
from .on_focus_consumer import OnFocusConsumer


def build_default_navigator_consumers() -> list[BaseConsumer]:
    return [
        FocusVisibleConsumer(),
        LinkPurposeConsumer(),
        OnFocusConsumer(),
        NoKeyboardTrapConsumer(),
    ]


__all__ = [
    "BaseConsumer",
    "FocusVisibleConsumer",
    "LinkPurposeConsumer",
    "OnFocusConsumer",
    "NoKeyboardTrapConsumer",
    "build_default_navigator_consumers",
]
