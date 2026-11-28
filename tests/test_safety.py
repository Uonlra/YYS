from __future__ import annotations

import logging
import unittest
from unittest.mock import patch

from pynput import keyboard

from src.yys_automation.safety import StopController


class StopControllerTests(unittest.TestCase):
    def test_escape_does_not_stop_automation(self) -> None:
        controller = StopController(logging.getLogger(__name__))

        self.assertIsNone(controller._on_press(keyboard.Key.esc))
        self.assertFalse(controller.should_stop)

    def test_stop_hotkey_requires_both_modifiers(self) -> None:
        controller = StopController(logging.getLogger(__name__))
        q = keyboard.KeyCode.from_char("q")

        controller._on_press(keyboard.Key.ctrl_l)
        self.assertIsNone(controller._on_press(q))
        controller._on_release(q)
        controller._on_press(keyboard.Key.shift_r)
        controller._on_release(keyboard.Key.ctrl_l)
        self.assertIsNone(controller._on_press(q))
        self.assertFalse(controller.should_stop)

        controller._on_release(q)
        controller._on_press(keyboard.Key.ctrl_r)
        with self.assertLogs(__name__, level="WARNING"):
            self.assertIs(controller._on_press(q), False)
        self.assertTrue(controller.should_stop)

    def test_windows_stop_hotkey_accepts_control_character(self) -> None:
        controller = StopController(logging.getLogger(__name__))
        q = keyboard.KeyCode(vk=ord("Q"), char="\x11")

        # Use the callbacks registered with the listener without sending real input.
        with patch("src.yys_automation.safety.keyboard.Listener") as listener:
            controller.start()
            on_press = listener.call_args.kwargs["on_press"]
            on_press(keyboard.Key.ctrl_l)
            on_press(keyboard.Key.shift_l)
            with self.assertLogs(__name__, level="WARNING"):
                self.assertIs(on_press(q), False)

        self.assertTrue(controller.should_stop)
