from .base import MobileBaseConsumer
from .missing_label import MissingLabelConsumer
from .touch_target import TouchTargetConsumer


def build_default_mobile_consumers() -> list[MobileBaseConsumer]:
    return [MissingLabelConsumer(), TouchTargetConsumer()]


__all__ = [
    "MobileBaseConsumer",
    "MissingLabelConsumer",
    "TouchTargetConsumer",
    "build_default_mobile_consumers",
]
