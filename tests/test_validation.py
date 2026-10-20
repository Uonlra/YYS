from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

import cv2
import numpy as np
import yaml

from src.yys_automation.config import load_config
from src.yys_automation.scenario import load_scenario, validate_scenario
from src.yys_automation.screen import ScreenCapture


class ValidationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.image = self.root / "target.png"
        cv2.imwrite(str(self.image), np.zeros((8, 8, 3), dtype=np.uint8))
        self.config = {
            "target_image": "target.png",
            "capture_mode": "window",
            "window": {"title_contains": "Test", "reference_width": 100, "reference_height": 50},
            "allowed_region": {"left": 0, "top": 0, "width": 100, "height": 50},
        }

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_config(self, values: dict[str, object] | None = None) -> Path:
        path = self.root / "config.yaml"
        path.write_text(yaml.safe_dump(values or self.config), encoding="utf-8")
        return path

    def test_string_false_is_not_accepted_as_boolean(self) -> None:
        config = {**self.config, "dry_run": "false"}
        with self.assertRaisesRegex(ValueError, "dry_run must be a boolean"):
            load_config(self.write_config(config))

    def test_non_finite_values_are_rejected(self) -> None:
        config = {**self.config, "scan_interval_seconds": float("nan")}
        with self.assertRaisesRegex(ValueError, "finite number"):
            load_config(self.write_config(config))

    def test_window_allowlist_must_fit_reference_size(self) -> None:
        config = {**self.config, "allowed_region": {"left": 90, "top": 0, "width": 20, "height": 10}}
        with self.assertRaisesRegex(ValueError, "exceeds reference_width"):
            load_config(self.write_config(config))

    def test_undecodable_target_is_rejected(self) -> None:
        bad_image = self.root / "bad.png"
        bad_image.write_text("not an image", encoding="utf-8")
        config = {**self.config, "target_image": "bad.png"}
        with self.assertRaisesRegex(ValueError, "cannot be decoded"):
            load_config(self.write_config(config))

    def test_duplicate_step_ids_are_rejected(self) -> None:
        scenario = self.root / "duplicate.yaml"
        scenario.write_text(
            "steps:\n  - id: same\n    type: wait\n  - id: same\n    type: wait\n",
            encoding="utf-8",
        )
        self.assertTrue(any("duplicate id" in error for error in validate_scenario(scenario)))

    def test_preflight_rejects_undecodable_step_image(self) -> None:
        bad_image = self.root / "bad.png"
        bad_image.write_text("not an image", encoding="utf-8")
        scenario = self.root / "bad-image.yaml"
        scenario.write_text(
            "steps:\n  - id: match\n    type: match_and_click\n    image: bad.png\n",
            encoding="utf-8",
        )
        self.assertTrue(any("cannot be decoded" in error for error in validate_scenario(scenario)))

    def test_preflight_checks_click_point_against_configured_allowlist(self) -> None:
        scenario = self.root / "point.yaml"
        scenario.write_text(
            "steps:\n  - id: point\n    type: click_point\n    x: 5\n    y: 5\n",
            encoding="utf-8",
        )
        config = load_config(self.write_config())
        config = replace(config, allowed_region=replace(config.allowed_region, left=10, top=10, width=20, height=20))
        self.assertTrue(any("outside allowed_region" in error for error in validate_scenario(scenario, config)))

    def test_screen_capture_context_closes_mss_resource(self) -> None:
        class FakeMss:
            closed = False

            def close(self) -> None:
                self.closed = True

        capture = ScreenCapture.__new__(ScreenCapture)
        capture._sct = FakeMss()
        with capture:
            self.assertFalse(capture._sct.closed)
        self.assertTrue(capture._sct.closed)

    def test_wait_for_image_requires_template(self) -> None:
        scenario = self.root / "observe.yaml"
        scenario.write_text("steps:\n  - id: observe\n    type: wait_for_image\n", encoding="utf-8")
        self.assertTrue(any("image is required" in error for error in validate_scenario(scenario)))

    def test_repeat_count_validation(self) -> None:
        for count in (0, -1, True, 1.5, 801):
            with self.subTest(count=count):
                path = self.root / "repeat.yaml"
                path.write_text(yaml.safe_dump({
                    "repeat_count": count, "max_cycles": 800,
                    "steps": [{"id": "pause", "type": "wait"}],
                }), encoding="utf-8")
                self.assertTrue(validate_scenario(path))

    def test_repeat_settings_load_with_safe_defaults(self) -> None:
        path = self.root / "repeat.yaml"
        for settings, expected in (({}, 1), ({"repeat_count": None}, None), ({"repeat_count": 800}, 800)):
            with self.subTest(settings=settings):
                path.write_text(yaml.safe_dump({
                    **settings, "steps": [{"id": "pause", "type": "wait"}],
                }), encoding="utf-8")
                scenario = load_scenario(path)
                self.assertEqual(scenario.repeat_count, expected)
                self.assertEqual(scenario.max_cycles, 800)

    def test_invalid_cycle_limit_is_rejected(self) -> None:
        path = self.root / "cycles.yaml"
        for limit in (0, -1, True, 1.5, None):
            with self.subTest(limit=limit):
                path.write_text(yaml.safe_dump({
                    "max_cycles": limit, "repeat_count": None,
                    "steps": [{"id": "pause", "type": "wait"}],
                }), encoding="utf-8")
                self.assertTrue(validate_scenario(path))


if __name__ == "__main__":
    unittest.main()
