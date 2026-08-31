import unittest
from dataclasses import asdict

from mobile_agent import _keyboard_from_data
from mobile_tools.base import MobileElementInfo, MobileKeyboardResult
from mobile_tools.consumers.keyboard_accessibility import KeyboardAccessibilityConsumer
from mobile_tools.screen_scanner import MobileScanSnapshot


class KeyboardAccessibilityConsumerTest(unittest.TestCase):
    def test_reachable_elements_pass(self) -> None:
        result = _consume(reachable=[_element(1, "Apri")])

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["issue_list"], [])
        self.assertEqual(result["score_passed"].level_A, 1)
        self.assertEqual(result["score_total"].level_A, 1)

    def test_unreachable_element_fails(self) -> None:
        result = _consume(unreachable=[_element(2, "Continua")])

        self.assertEqual(result["checked"], 1)
        self.assertEqual(len(result["issue_list"]), 1)
        self.assertIn("2.1.1 - Keyboard", result["issue_list"][0]["wcag_rule"])
        self.assertEqual(result["issue_list"][0]["confidence"], "medium")
        self.assertEqual(result["score_passed"].level_A, 0)

    def test_reachable_and_unreachable_elements_are_scored(self) -> None:
        result = _consume(
            reachable=[_element(1, "Apri"), _element(2, "Chiudi")],
            unreachable=[_element(3, "Continua")],
        )

        self.assertEqual(result["checked"], 3)
        self.assertEqual(len(result["issue_list"]), 1)
        self.assertEqual(result["score_passed"].level_A, 2)
        self.assertEqual(result["score_total"].level_A, 3)

    def test_duplicate_element_is_counted_once(self) -> None:
        element = _element(1, "Apri")
        consumer = KeyboardAccessibilityConsumer()
        keyboard_result = _keyboard_result(reachable=[element])

        consumer.consume_keyboard(keyboard_result)
        consumer.consume_keyboard(keyboard_result)
        result = consumer.finalize()

        self.assertEqual(result["checked"], 1)
        self.assertEqual(result["score_passed"].level_A, 1)

    def test_empty_traversal_has_zero_score(self) -> None:
        result = _consume()

        self.assertEqual(result["checked"], 0)
        self.assertEqual(result["issue_list"], [])
        self.assertEqual(result["score_total"].level_A, 0)

    def test_serialized_elements_survive_snapshot_deserialization(self) -> None:
        reachable = _element(1, "Apri")
        unreachable = _element(2, "Continua")
        snapshot = MobileScanSnapshot(
            activity="com.example.MainActivity",
            tree_xml="<hierarchy />",
            screenshot="",
            elements=[],
        )

        result = _keyboard_from_data(
            {
                "reachable": [asdict(reachable)],
                "unreachable": [asdict(unreachable)],
                "focus_order": [asdict(reachable)],
                "traps": [{"focus_key": reachable.get_focus_key(), "step": 2}],
                "activity": "com.example.MainActivity",
            },
            snapshot,
        )

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.reachable, [reachable])
        self.assertEqual(result.unreachable, [unreachable])
        self.assertEqual(result.focus_order, [reachable])
        self.assertEqual(result.traps, [{"focus_key": reachable.get_focus_key(), "step": 2}])


def _consume(
    *,
    reachable: list[MobileElementInfo] | None = None,
    unreachable: list[MobileElementInfo] | None = None,
) -> dict:
    consumer = KeyboardAccessibilityConsumer()
    consumer.consume_keyboard(_keyboard_result(reachable=reachable, unreachable=unreachable))
    return consumer.finalize()


def _keyboard_result(
    *,
    reachable: list[MobileElementInfo] | None = None,
    unreachable: list[MobileElementInfo] | None = None,
) -> MobileKeyboardResult:
    return MobileKeyboardResult(
        reachable=reachable or [],
        unreachable=unreachable or [],
        focus_order=[],
        traps=[],
        activity="com.example.MainActivity",
    )


def _element(index: int, label: str) -> MobileElementInfo:
    return MobileElementInfo(
        index=index,
        text=label,
        class_name="android.widget.Button",
        bounds=f"[{index * 10},0][{index * 10 + 100},100]",
        clickable=True,
    )


if __name__ == "__main__":
    unittest.main()
