import unittest

from mobile_tools.base import MobileElementInfo, MobileNavigatorState
from mobile_tools.consumers.label_in_name import LabelInNameConsumer


class LabelInNameConsumerTest(unittest.TestCase):
    def test_matching_visible_label_passes(self) -> None:
        result = _consume(text="Continua", content_desc="Continua al pagamento")

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["issue_list"], [])
        self.assertEqual(result["score_passed"].level_A, 1)

    def test_comparison_ignores_case_spacing_and_punctuation(self) -> None:
        result = _consume(text="  Continua! ", content_desc="CONTINUA, al pagamento")

        self.assertEqual(result["issue_list"], [])

    def test_different_accessible_name_fails(self) -> None:
        result = _consume(text="Continua", content_desc="Vai avanti")

        self.assertEqual(result["checked"], 1)
        self.assertEqual(len(result["issue_list"]), 1)
        self.assertIn("2.5.3 - Label in Name", result["issue_list"][0]["wcag_rule"])
        self.assertEqual(result["score_passed"].level_A, 0)

    def test_visible_text_is_name_when_content_description_is_missing(self) -> None:
        result = _consume(text="Continua", content_desc=None)

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["issue_list"], [])

    def test_control_without_visible_text_is_out_of_scope(self) -> None:
        result = _consume(text=None, content_desc="Apri menu")

        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["issue_list"], [])

    def test_symbolic_visible_text_is_out_of_scope(self) -> None:
        result = _consume(text=">", content_desc="Avanti")

        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["issue_list"], [])

    def test_non_interactive_element_is_out_of_scope(self) -> None:
        result = _consume(text="Continua", content_desc="Vai avanti", interactive=False)

        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["issue_list"], [])


def _consume(
    *,
    text: str | None,
    content_desc: str | None,
    interactive: bool = True,
) -> dict:
    consumer = LabelInNameConsumer()
    consumer.consume(
        MobileNavigatorState(
            path=[],
            activity="com.example.MainActivity",
            current_element=MobileElementInfo(
                index=1,
                text=text,
                content_desc=content_desc,
                class_name="android.widget.Button",
                bounds="[0,0][100,100]",
                clickable=interactive,
            ),
        )
    )
    return consumer.finalize()


if __name__ == "__main__":
    unittest.main()
