from __future__ import annotations

import logging
import unittest
from pathlib import Path
from unittest.mock import patch

from src.yys_automation.config import AppConfig, DurationRange, Jitter, Region, WindowConfig
from src.yys_automation.clicker import HumanLikeClicker


class ClickerTests(unittest.TestCase):
    def make_config(self) -> AppConfig:
        return AppConfig(
            target_image=Path("unused.png"), threshold=0.86,
            allowed_region=Region(0, 0, 1280, 720), scan_interval_seconds=0.25,
            min_click_interval_seconds=1, max_clicks=1,
            move_duration_seconds=DurationRange(0.3, 0.3), click_jitter_pixels=Jitter(0, 0),
            startup_delay_seconds=0, dry_run=False, log_file=Path("unused.log"),
            window=WindowConfig("test", 1280, 720), capture_mode="window",
            template_scale_min=1, template_scale_max=1, template_scale_step=0.1,
        )

    def test_physical_click_moves_smoothly_then_sends_mouse_click(self) -> None:
        logger = logging.getLogger("test_human_clicker")
        clicker = HumanLikeClicker(self.make_config(), logger)
        calls = []
        with patch("src.yys_automation.clicker.random.uniform", return_value=0.3), \
             patch("src.yys_automation.clicker.pyautogui.moveTo", side_effect=lambda *args, **kwargs: calls.append(("move", args, kwargs))), \
             patch("src.yys_automation.clicker.pyautogui.position", return_value=type("Position", (), {"x": 400, "y": 300})()), \
             patch("src.yys_automation.clicker.pyautogui.click", side_effect=lambda: calls.append(("click", (), {}))):
            with self.assertLogs(logger, level="INFO") as logs:
                clicker.click(400, 300)

        self.assertEqual(calls[0], ("move", (400, 300), {"duration": 0.3}))
        self.assertEqual(calls[1][0], "click")
        self.assertTrue(any("Physical mouse click sent at x=400 y=300" in item for item in logs.output))


if __name__ == "__main__":
    unittest.main()
