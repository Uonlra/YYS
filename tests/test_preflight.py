from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

import cv2
import numpy as np

from src.yys_automation.config import Region
from src.yys_automation.preflight import capture_preview, inspect_frame, with_window_identity
from src.yys_automation.preflight_gui import selection_region
from src.yys_automation.recognition_pane import compare_thresholds
from src.yys_automation.scenario import Scenario, ScenarioStep
from src.yys_automation.screen import Frame
from src.yys_automation.window import WindowInfo, WindowLocator
from test_workflow import make_config


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.image = Path(self.temp.name) / "target.png"
        template = np.random.default_rng(42).integers(0, 255, (12, 14, 3), dtype=np.uint8)
        cv2.imwrite(str(self.image), template)
        frame = np.zeros((50, 100, 3), dtype=np.uint8)
        frame[15:27, 20:34] = template
        self.frame = Frame(frame, 1000, 500, 2, 2)
        self.window = WindowInfo(123, "Preview test", 1000, 500, 200, 100, 456)
        self.config = make_config()
        self.step = ScenarioStep("start", "match_and_click", self.image, 0.95, 30, None, None, 1)
        self.scenario = Scenario("preview", 1, False, (self.step,), execution_mode="match_any")

    def test_drag_maps_scaled_and_centered_image_in_both_directions(self):
        displayed = Region(20, 30, 320, 180)
        expected = Region(160, 80, 800, 600)
        self.assertEqual(selection_region((60, 50), (260, 200), displayed, 1280, 720), expected)
        self.assertEqual(selection_region((260, 200), (60, 50), displayed, 1280, 720), expected)

    def test_drag_clips_at_image_boundary_and_ignores_outside_press(self):
        displayed = Region(20, 30, 320, 180)
        self.assertEqual(selection_region((320, 205), (500, 300), displayed, 1280, 720),
                         Region(1200, 700, 80, 20))
        self.assertIsNone(selection_region((19, 30), (300, 200), displayed, 1280, 720))
        self.assertIsNone(selection_region((30, 40), (31, 45), displayed, 1280, 720))

    def test_preview_draws_match_and_maps_center_without_modifying_frame(self):
        before = self.frame.image.copy()
        result = inspect_frame(self.config, self.scenario, self.frame, self.window)
        item = result.targets[0]
        self.assertTrue(item.matched)
        self.assertEqual(item.point, (27, 21))
        self.assertEqual(item.screen_point, (1054, 542))
        self.assertTrue(item.in_bounds)
        self.assertEqual(result.preferred_id, "start")
        np.testing.assert_array_equal(before, self.frame.image)
        self.assertFalse(np.array_equal(result.annotated, before))

    def test_search_uses_the_same_allowlist_as_runtime(self):
        config = replace(self.config, allowed_region=Region(50, 0, 50, 50))
        result = inspect_frame(config, self.scenario, self.frame, self.window)
        self.assertFalse(result.targets[0].matched)
        self.assertIsNone(result.targets[0].point)
        self.assertIsNone(result.preferred_id)

    def test_fractional_scaling_uses_runtime_box_center_rounding(self):
        frame = replace(self.frame, scale_x=1.1, scale_y=1.1)
        result = inspect_frame(self.config, self.scenario, frame, self.window)
        self.assertEqual(result.targets[0].screen_point, (1029, 522))

    def test_tied_matches_follow_config_order(self):
        scenario = replace(self.scenario, steps=(replace(self.step, id="victory"), self.step))
        result = inspect_frame(self.config, scenario, self.frame, self.window)
        self.assertEqual(result.preferred_id, "victory")

    def test_threshold_comparison_uses_same_raw_frame_and_only_selected_target(self):
        altered = self.frame.image.copy()
        altered[15:19, 20:34] = 0
        frame = replace(self.frame, image=altered)
        step = replace(self.step, id="victory", threshold=0.99)
        scenario = replace(self.scenario, steps=(replace(self.step, image=Path("unused.png")), step))
        result = compare_thresholds(self.config, scenario, step, frame, self.window, 0.5)
        before, after = result.current.targets[0], result.draft.targets[0]
        self.assertIs(result.current.frame, result.draft.frame)
        self.assertEqual([item.id for item in result.draft.targets], ["victory"])
        self.assertFalse(before.matched)
        self.assertIsNotNone(before.box)
        self.assertIsNone(before.point)
        self.assertTrue(after.matched)
        self.assertEqual(after.point, (27, 21))
        self.assertEqual(before.score, after.score)
        self.assertEqual(scenario.steps[1].threshold, 0.99)

    def test_observation_step_has_no_click_point(self):
        scenario = replace(self.scenario, execution_mode="sequential", steps=(replace(self.step, type="wait_for_image"),))
        result = inspect_frame(self.config, scenario, self.frame, self.window, "start")
        self.assertTrue(result.targets[0].matched)
        self.assertIsNone(result.targets[0].point)
        self.assertIsNone(result.preferred_id)

    def test_sequential_preview_only_checks_selected_step(self):
        scenario = replace(self.scenario, execution_mode="sequential", steps=(self.step, replace(self.step, id="reward")))
        result = inspect_frame(self.config, scenario, self.frame, self.window, "reward")
        self.assertEqual([item.id for item in result.targets], ["reward"])

    def test_out_of_bounds_point_is_reported(self):
        step = replace(self.step, type="click_point", image=None, threshold=None, x=100, y=0)
        scenario = replace(self.scenario, execution_mode="sequential", steps=(step,))
        result = inspect_frame(self.config, scenario, self.frame, self.window, "start")
        self.assertFalse(result.targets[0].in_bounds)
        self.assertEqual(result.targets[0].point, (100, 0))

    def test_capture_pins_identity_and_preserves_config(self):
        with patch("src.yys_automation.preflight.WindowLocator") as locator, \
             patch("src.yys_automation.preflight.WindowScreenCapture") as source:
            locator.return_value.find_first.return_value = self.window
            source.return_value.grab.return_value = self.frame
            result = capture_preview(self.config, self.scenario)
        bound = source.call_args.args[0]
        self.assertEqual((bound.handle, bound.process_id), (123, 456))
        self.assertEqual(bound.title_contains, "")
        self.assertIsNone(self.config.window.handle)
        self.assertEqual(result.window.title, "Preview test")

    def test_missing_window_does_not_capture(self):
        with patch("src.yys_automation.preflight.WindowLocator") as locator, \
             patch("src.yys_automation.preflight.WindowScreenCapture") as source:
            locator.return_value.find_first.return_value = None
            with self.assertRaisesRegex(ValueError, "未找到"):
                capture_preview(self.config, self.scenario)
        source.assert_not_called()

    def test_override_does_not_change_reference_geometry(self):
        config = with_window_identity(self.config, (12, 34))
        self.assertEqual(config.window.reference_width, self.config.window.reference_width)
        self.assertEqual(config.allowed_region, self.config.allowed_region)
        self.assertEqual(config.window.title_contains, "")
        for identity in ((0, 34), (12, -1), (True, 34)):
            with self.assertRaises(ValueError):
                with_window_identity(self.config, identity)

    def test_find_first_remains_compatible_with_enumeration(self):
        locator = WindowLocator()
        with patch.object(locator, "find_all", return_value=[self.window]) as find_all:
            self.assertEqual(locator.find_first("Preview", handle=123, process_id=456), self.window)
        find_all.assert_called_once_with("Preview", handle=123, process_id=456)


if __name__ == "__main__":
    unittest.main()
