"""Deterministic mobile accessibility consumers."""

from .form_label import FormLabelConsumer
from .label_in_name import LabelInNameConsumer
from .meaningful_sequence import MeaningfulSequenceConsumer
from .name_role_value import NameRoleValueConsumer
from .non_text_content import NonTextContentConsumer
from .page_titled import PageTitledConsumer
from .runner import DeterministicRunner
from .touch_target import TouchTargetConsumer

__all__ = [
    "DeterministicRunner",
    "FormLabelConsumer",
    "LabelInNameConsumer",
    "NameRoleValueConsumer",
    "MeaningfulSequenceConsumer",
    "NonTextContentConsumer",
    "PageTitledConsumer",
    "TouchTargetConsumer",
]
