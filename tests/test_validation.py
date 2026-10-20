from __future__ import annotations

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import Mock, patch

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

    def test_task_budget_rejects_invalid_values(self) -> None:
        path = self.root / "budget.yaml"
        for value in (None, -1, True, 1.5, "10", "unlimited", float("inf")):
            with self.subTest(value=value):
                path.write_text(yaml.safe_dump({
                    "max_clicks": value, "steps": [{"id": "pause", "type": "wait"}],
                }), encoding="utf-8")
                self.assertTrue(any("max_clicks" in error for error in validate_scenario(path)))

    def test_task_budget_preserves_missing_auto_and_integer_settings(self) -> None:
        path = self.root / "budget.yaml"
        for settings, expected in (({}, None), ({"max_clicks": "auto"}, "auto"), ({"max_clicks": 0}, 0), ({"max_clicks": 20}, 20)):
            with self.subTest(settings=settings):
                path.write_text(yaml.safe_dump({
                    **settings, "steps": [{"id": "pause", "type": "wait"}],
                }), encoding="utf-8")
                self.assertEqual(load_scenario(path).max_clicks, expected)

    def test_gui_saves_preserve_task_budget_and_global_fallback(self) -> None:
        from src.yys_automation.config_gui import ScenarioEditor

        path = self.root / "gui.yaml"
        for value in (None, "auto", 0, 500):
            for method in ("_save", "_save_silently"):
                with self.subTest(value=value, method=method):
                    payload = {"steps": [{"id": "pause", "type": "wait"}]}
                    if value is not None:
                        payload["max_clicks"] = value
                    path.write_text(yaml.safe_dump(payload), encoding="utf-8")
                    editor = ScenarioEditor.__new__(ScenarioEditor)
                    editor.scenario = load_scenario(path)
                    editor.steps = list(editor.scenario.steps)
                    editor.path_var = Mock()
                    editor.path_var.get.return_value = str(path)
                    with patch("src.yys_automation.config_gui.messagebox") as messages:
                        getattr(editor, method)()
                        messages.showerror.assert_not_called()
                    saved = yaml.safe_load(path.read_text(encoding="utf-8"))
                    self.assertEqual(saved.get("max_clicks"), value)
                    if value is None:
                        self.assertNotIn("max_clicks", saved)

    def test_state_recovery_rejects_invalid_references_and_retry_settings(self) -> None:
        path = self.root / "recovery.yaml"
        cases = [
            {"max_attempts": 0}, {"max_attempts": 4}, {"max_attempts": True},
            {"max_attempts": 2}, {"next_step": "missing"}, {"next_step": "first"},
            {"recover_to": ["first"]}, {"recover_to": ["missing"]},
            {"recover_to": "second"}, {"response_timeout_seconds": 0},
            {"response_timeout_seconds": float("inf")},
        ]
        for settings in cases:
            with self.subTest(settings=settings):
                path.write_text(yaml.safe_dump({"steps": [
                    {"id": "first", "type": "match_and_click", "image": "target.png", **settings},
                    {"id": "second", "type": "wait_for_image", "image": "target.png"},
                ]}), encoding="utf-8")
                self.assertTrue(validate_scenario(path))

    def test_recovery_cannot_target_unchecked_coordinate_step(self) -> None:
        path = self.root / "coordinate.yaml"
        path.write_text(yaml.safe_dump({"steps": [
            {"id": "first", "type": "match_and_click", "image": "target.png", "recover_to": ["second"]},
            {"id": "second", "type": "click_point", "image": "target.png", "x": 10, "y": 10},
        ]}), encoding="utf-8")
        self.assertTrue(any("revalidate" in error for error in validate_scenario(path)))

    def test_recovery_scan_limits_and_intervals_are_validated(self) -> None:
        path = self.root / "recovery.yaml"
        for settings in ({"recovery_scans": 3}, {"recovery_scans": -1}, {"recovery_scans": True},
                         {"recovery_interval_seconds": 0}, {"recovery_interval_seconds": float("nan")}):
            with self.subTest(settings=settings):
                path.write_text(yaml.safe_dump({**settings, "steps": [{"id": "pause", "type": "wait"}]}), encoding="utf-8")
                self.assertTrue(validate_scenario(path))

    def test_gui_roundtrip_preserves_state_confirmation_and_recovery(self) -> None:
        from src.yys_automation.config_gui import ScenarioEditor

        path = self.root / "recovery.yaml"
        payload = {"stable_frames": 3, "recovery_scans": 2, "recovery_interval_seconds": 1.5, "steps": [
            {"id": "first", "type": "match_and_click", "image": "target.png", "max_attempts": 3,
             "next_step": "second", "response_timeout_seconds": 2.5, "recover_to": ["second"]},
            {"id": "second", "type": "wait_for_image", "image": "target.png", "requires_action": "first"},
        ]}
        for method in ("_save", "_save_silently"):
            with self.subTest(method=method):
                path.write_text(yaml.safe_dump(payload), encoding="utf-8")
                original = load_scenario(path)
                editor = ScenarioEditor.__new__(ScenarioEditor)
                editor.scenario = original
                editor.steps = list(original.steps)
                editor.path_var = Mock()
                editor.path_var.get.return_value = str(path)
                with patch("src.yys_automation.config_gui.messagebox") as messages:
                    getattr(editor, method)()
                    messages.showerror.assert_not_called()
                self.assertEqual(load_scenario(path), original)

    def test_stable_frames_validation(self) -> None:
        path = self.root / "stable.yaml"
        for value in (0, -1, 11, True, 1.5, None):
            with self.subTest(value=value):
                path.write_text(yaml.safe_dump({"stable_frames": value, "steps": [{"id": "pause", "type": "wait"}]}), encoding="utf-8")
                self.assertTrue(any("stable_frames" in error for error in validate_scenario(path)))

    def test_requires_action_must_reference_earlier_click_and_only_guard_observer(self) -> None:
        path = self.root / "phase.yaml"
        for target, step_type in (("missing", "wait_for_image"), ("end", "wait_for_image"),
                                  ("pause", "wait_for_image"), (True, "wait_for_image"),
                                  ("click", "match_and_click")):
            with self.subTest(target=target, step_type=step_type):
                path.write_text(yaml.safe_dump({"steps": [
                    {"id": "click", "type": "click_point", "x": 1, "y": 1},
                    {"id": "pause", "type": "wait"},
                    {"id": "end", "type": step_type, "image": "target.png", "requires_action": target},
                ]}), encoding="utf-8")
                self.assertTrue(any("requires_action" in error for error in validate_scenario(path)))


if __name__ == "__main__":
    unittest.main()
