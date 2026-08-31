import unittest

from mobile_tools.base import MobileElementInfo, MobileNavigatorState
from mobile_tools.consumers.non_text_content import NonTextContentConsumer


class NonTextContentConsumerTest(unittest.TestCase):
    def test_image_with_content_description_passes(self) -> None:
        result = _consume(class_name="android.widget.ImageView", content_desc="Logo aziendale", clickable=True)

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["issue_list"], [])
        self.assertEqual(result["score_passed"].level_A, 1)

    def test_image_with_visible_text_passes(self) -> None:
        result = _consume(class_name="android.widget.ImageView", text="Profilo", clickable=True)

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["issue_list"], [])

    def test_interactive_image_without_alternative_fails_with_high_confidence(self) -> None:
        result = _consume(class_name="android.widget.ImageButton", clickable=True)

        self.assertEqual(result["checked"], 1)
        self.assertEqual(len(result["issue_list"]), 1)
        self.assertIn("1.1.1 - Non-text Content", result["issue_list"][0]["wcag_rule"])
        self.assertEqual(result["issue_list"][0]["confidence"], "high")
        self.assertEqual(result["score_passed"].level_A, 0)

    def test_non_interactive_image_is_out_of_scope(self) -> None:
        result = _consume(class_name="android.widget.ImageView")

        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["issue_list"], [])

    def test_non_image_is_out_of_scope(self) -> None:
        result = _consume(class_name="android.widget.Button", clickable=True)

        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["issue_list"], [])

    def test_duplicate_element_is_checked_once(self) -> None:
        consumer = NonTextContentConsumer()
        state = _state(class_name="android.widget.ImageButton", clickable=True)

        consumer.consume(state)
        consumer.consume(state)
        result = consumer.finalize()

        self.assertEqual(result["checked"], 1)
        self.assertEqual(len(result["issue_list"]), 1)


def _consume(
    *,
    class_name: str,
    text: str | None = None,
    content_desc: str | None = None,
    clickable: bool = False,
) -> dict:
    consumer = NonTextContentConsumer()
    consumer.consume(
        _state(
            class_name=class_name,
            text=text,
            content_desc=content_desc,
            clickable=clickable,
        )
    )
    return consumer.finalize()


def _state(
    *,
    class_name: str,
    text: str | None = None,
    content_desc: str | None = None,
    clickable: bool = False,
) -> MobileNavigatorState:
    return MobileNavigatorState(
        path=[],
        activity="com.example.MainActivity",
        current_element=MobileElementInfo(
            index=1,
            text=text,
            content_desc=content_desc,
            class_name=class_name,
            bounds="[0,0][100,100]",
            clickable=clickable,
        ),
    )


if __name__ == "__main__":
    unittest.main()
