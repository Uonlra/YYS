from __future__ import annotations

import tempfile
import unittest
import contextlib
import io
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import yaml

from run import init_config
from src.yys_automation.config import Region, load_config
from src.yys_automation.config_gui import ScenarioEditor
from src.yys_automation.editor_ui import TYPE_LABELS
from src.yys_automation.recent_scenarios import RecentScenario, RecentScenarios
from src.yys_automation.scenario import load_scenario


class EditorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root_path = Path(self.temp.name)
        self.config_path = self.root_path / "config.yaml"
        with contextlib.redirect_stdout(io.StringIO()):
            init_config(self.config_path)
        self.path = self.root_path / "scenario.yaml"
        self.path.write_text(yaml.safe_dump({"steps": [
            {"id": "first", "type": "wait", "timeout_seconds": 1},
            {"id": "second", "type": "click_point", "x": 0, "y": 0},
        ]}), encoding="utf-8")
        self.editor = ScenarioEditor(self.path, self.config_path)
        self.editor.root.withdraw()
        self.addCleanup(self.cleanup)

    def cleanup(self) -> None:
        if self.editor._poll_id:
            self.editor.root.after_cancel(self.editor._poll_id)
        self.editor._remove_output()
        self.editor.root.destroy()
        self.temp.cleanup()

    def test_save_applies_form_without_explicit_update(self) -> None:
        self.editor.form["timeout"].set("4.5")
        self.assertTrue(self.editor._save_silently())
        self.assertEqual(load_scenario(self.path).steps[0].timeout_seconds, 4.5)
        self.assertFalse(self.editor._dirty)

    def test_resume_restores_saved_scenario_and_step_without_running(self) -> None:
        self.editor.tree.selection_set("1")
        self.editor._select_step(None)
        other = self.root_path / "fallback.yaml"
        other.write_text("steps: [{id: fallback, type: wait}]", encoding="utf-8")
        with patch("src.yys_automation.config_gui.subprocess.Popen") as launch:
            resumed = ScenarioEditor(other, self.config_path, restore_recent=True)
            self.addCleanup(resumed.root.destroy)
            resumed.root.withdraw()
            self.assertEqual(resumed.scenario_path, self.path)
            self.assertEqual(resumed.form["id"].get(), "second")
            self.assertEqual(resumed.status_var.get(), "就绪")
        launch.assert_not_called()
        explicit = ScenarioEditor(other, self.config_path)
        self.addCleanup(explicit.root.destroy)
        explicit.root.withdraw()
        self.assertEqual(explicit.scenario_path, other)
        self.assertEqual(explicit.form["id"].get(), "fallback")

    def test_recent_menu_reopens_previous_scene_at_its_selected_step(self) -> None:
        self.editor.tree.selection_set("1")
        self.editor._select_step(None)
        other = self.root_path / "other.yaml"
        other.write_text("steps: [{id: other, type: wait}]", encoding="utf-8")
        self.assertTrue(self.editor._load_file(other))
        self.editor._refresh_recent_menu()
        self.assertEqual(self.editor.recent_menu.entrycget(0, "label"), "other.yaml")
        self.editor.recent_menu.invoke(1)
        self.assertEqual(self.editor.scenario_path, self.path)
        self.assertEqual(self.editor.form["id"].get(), "second")

    def test_missing_scene_can_be_relocated_and_keeps_step_selection(self) -> None:
        self.editor.tree.selection_set("1")
        self.editor._select_step(None)
        moved = self.path.rename(self.root_path / "moved.yaml")
        resumed = ScenarioEditor(None, self.config_path, restore_recent=True)
        self.addCleanup(resumed.root.destroy)
        resumed.root.withdraw()
        self.assertIsNone(resumed.scenario_path)
        self.assertEqual(Path(resumed.path_var.get()), self.path)
        self.assertIn("找不到场景", resumed.file_notice_var.get())
        self.assertTrue(resumed.file_notice.winfo_manager())
        with patch("src.yys_automation.config_gui.filedialog.askopenfilename", return_value=str(moved)):
            resumed.relocate_button.invoke()
        self.assertEqual(resumed.scenario_path, moved)
        self.assertEqual(resumed.form["id"].get(), "second")
        self.assertFalse(resumed.file_notice.winfo_manager())
        self.assertEqual(RecentScenarios(self.config_path).entries, [RecentScenario(moved, "second")])

    def test_resume_falls_back_to_first_step_if_saved_step_no_longer_exists(self) -> None:
        self.editor.recent.remember(self.path, "renamed_step")
        resumed = ScenarioEditor(None, self.config_path, restore_recent=True)
        self.addCleanup(resumed.root.destroy)
        resumed.root.withdraw()
        self.assertEqual(resumed.form["id"].get(), "first")

    def test_saving_before_loading_typed_path_writes_only_the_original_scene(self) -> None:
        other = self.root_path / "other.yaml"
        content = "steps: [{id: other, type: wait}]"
        other.write_text(content, encoding="utf-8")
        self.editor.form["timeout"].set("6")
        self.editor.path_var.set(str(other))
        with patch("src.yys_automation.config_gui.messagebox.askyesnocancel", return_value=True):
            self.editor._load_from_entry()
        self.assertEqual(load_scenario(self.path).steps[0].timeout_seconds, 6)
        self.assertEqual(other.read_text(encoding="utf-8"), content)
        self.assertEqual(self.editor.scenario_path, other)

    def test_launch_budget_tracks_global_override_and_current_step_draft(self) -> None:
        self.editor._global_settings_saved(replace(load_config(self.config_path), max_clicks=22))
        self.assertEqual((self.editor.budget_var.get(), self.editor.budget_source_var.get()),
                         ("22 次", "继承全局设置"))
        self.editor._apply_scenario_settings({"max_clicks": 0})
        self.assertEqual((self.editor.budget_var.get(), self.editor.budget_source_var.get()),
                         ("0 次", "场景覆盖全局设置"))
        self.editor._apply_scenario_settings({"max_clicks": "auto"})
        self.assertEqual((self.editor.budget_var.get(), self.editor.budget_source_var.get()),
                         ("1 次", "场景自动计算"))
        self.editor.tree.selection_set("1")
        self.editor._select_step(None)
        self.editor.form["attempts"].set("3")
        self.assertEqual(self.editor.budget_var.get(), "3 次")
        self.editor.form["attempts"].set("oops")
        self.assertEqual(self.editor.budget_var.get(), "待校验")

    def test_launch_mode_and_window_show_the_effective_settings(self) -> None:
        self.assertIn("全局", self.editor.mode_var.get())
        self.assertIn("disabled", self.editor.dry_check.state())
        config = replace(load_config(self.config_path), dry_run=False)
        self.editor._global_settings_saved(config)
        self.assertEqual(self.editor.mode_var.get(), "真实点击")
        self.editor.dry_check.invoke()
        self.assertEqual(self.editor.run_button.cget("text"), "试运行场景")
        self.assertIn("本次会话", self.editor.mode_var.get())
        self.editor._apply_window((123, 456), "测试窗口")
        self.assertIn("测试窗口 · HWND 123", self.editor.window_var.get())
        self.editor._apply_window(None, "按全局配置定位")
        self.assertIn(config.window.title_contains, self.editor.window_var.get())

    def test_log_collects_output_while_collapsed_and_shows_latest_text_on_expand(self) -> None:
        self.assertFalse(self.editor.log_frame.winfo_manager())
        path = self.root_path / "worker.log"
        self.editor._output_path = path
        path.write_text("first line\n", encoding="utf-8")
        self.editor._poll_output()
        self.assertEqual(self.editor.log_text.get("1.0", "end-1c"), "")
        self.editor.log_button.invoke()
        self.assertEqual(self.editor.log_text.get("1.0", "end-1c"), "first line\n")
        self.assertEqual(self.editor.log_button.cget("text"), "收起日志")
        self.editor.log_button.invoke()
        path.write_text("first line\nsecond line\n", encoding="utf-8")
        self.editor._poll_output()
        self.editor.log_button.invoke()
        self.assertIn("second line", self.editor.log_text.get("1.0", "end-1c"))

    def test_single_step_starts_with_its_own_budget_in_run_summary(self) -> None:
        self.editor._apply_scenario_settings({"max_clicks": 20})
        self.editor.tree.selection_set("1")
        self.editor._select_step(None)
        with patch("src.yys_automation.config_gui.subprocess.Popen") as popen, \
             patch.object(self.editor, "_poll_process"):
            popen.return_value.poll.return_value = None
            self.editor._test_current_step()
        self.assertEqual(self.editor.budget_var.get(), "20 次")
        self.assertIn("点击 0 / 1", self.editor.run_summary_var.get())

    def test_invalid_form_does_not_overwrite_original(self) -> None:
        original = self.path.read_bytes()
        self.editor.form["timeout"].set("nan")
        with patch("src.yys_automation.config_gui.messagebox.showerror") as error:
            self.assertFalse(self.editor._save_silently())
        error.assert_called_once()
        self.assertEqual(self.path.read_bytes(), original)

    def test_invalid_transition_does_not_overwrite_original(self) -> None:
        original = self.path.read_bytes()
        self.editor.form["next"].set("does_not_exist")
        with patch("src.yys_automation.config_gui.messagebox.showerror") as error:
            self.assertFalse(self.editor._save_silently())
        error.assert_called_once()
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(list(self.root_path.glob("yys_step_*.yaml")), [])

    def test_zero_coordinates_survive_selection_and_save(self) -> None:
        self.editor.tree.selection_set("1")
        self.editor._select_step(None)
        self.assertEqual(self.editor.form["x"].get(), "0")
        self.assertEqual(self.editor.form["y"].get(), "0")
        self.assertTrue(self.editor._save_silently())
        self.assertEqual(load_scenario(self.path).steps[1].x, 0)
        self.assertEqual(self.editor._step_values(self.editor.steps[1])[5:7], ("0", "0"))

    def test_switching_steps_commits_previous_edits(self) -> None:
        self.editor.form["timeout"].set("8")
        self.editor.tree.selection_set("1")
        self.editor._select_step(None)
        self.assertEqual(self.editor.steps[0].timeout_seconds, 8)
        self.assertEqual(self.editor.form["id"].get(), "second")

    def test_duplicate_id_does_not_replace_step(self) -> None:
        self.editor.form["id"].set("second")
        with patch("src.yys_automation.config_gui.messagebox.showerror"):
            self.assertFalse(self.editor._commit_form())
        self.assertEqual(self.editor.steps[0].id, "first")

    def test_move_keeps_edits_and_selection(self) -> None:
        self.editor.form["timeout"].set("9")
        self.editor._move_step(1)
        self.assertEqual(self.editor.steps[1].id, "first")
        self.assertEqual(self.editor.steps[1].timeout_seconds, 9)
        self.assertEqual(self.editor.tree.selection(), ("1",))

    def test_validation_checks_current_form_without_saving(self) -> None:
        original = self.path.read_bytes()
        self.editor.tree.selection_set("1")
        self.editor._select_step(None)
        self.editor.form["x"].set("9999")
        with patch("src.yys_automation.config_gui.messagebox.showwarning") as warning:
            self.editor._validate()
        warning.assert_called_once()
        self.assertIn("outside", warning.call_args.args[1])
        self.assertEqual(self.path.read_bytes(), original)

    def test_cancel_loading_preserves_unsaved_form(self) -> None:
        self.editor.form["timeout"].set("7")
        with patch("src.yys_automation.config_gui.messagebox.askyesnocancel", return_value=None):
            self.editor._load_file(self.path)
        self.assertEqual(self.editor.form["timeout"].get(), "7")

    def test_stale_status_is_ignored(self) -> None:
        now = datetime.now(timezone.utc)
        self.editor._started_at = now
        self.editor.status_reader = Mock()
        self.editor.status_reader.read.return_value = {"updated_at": (now - timedelta(seconds=1)).isoformat()}
        self.assertIsNone(self.editor._fresh_status())
        current = {"updated_at": now.isoformat(), "clicks": 0}
        self.editor.status_reader.read.return_value = current
        self.assertEqual(self.editor._fresh_status(), current)

    def test_stop_does_not_block_ui_waiting_for_process(self) -> None:
        process = Mock()
        process.poll.return_value = None
        self.editor.process = process
        self.editor._stop_process()
        process.terminate.assert_called_once()
        process.wait.assert_not_called()
        self.assertEqual(self.editor.status_var.get(), "正在停止")

    def test_finished_process_retains_failure_reason(self) -> None:
        self.editor.process = Mock()
        self.editor.process.poll.return_value = 1
        self.editor._last_status = {"failure_reason": "bounds"}
        self.editor._poll_process()
        self.assertIn("点击位置超出允许区域", self.editor.detail_var.get())
        self.assertIsNone(self.editor.process)
        self.assertIn("disabled", self.editor.stop_button.state())
        self.assertNotIn("disabled", self.editor.diagnostic_button.state())

    def test_normal_budget_stop_opens_diagnostics(self) -> None:
        self.editor.process = Mock()
        self.editor.process.poll.return_value = 0
        self.editor._last_status = {"stop_reason": "budget", "clicks": 3, "max_clicks": 3}
        self.editor._run_editor_path = self.path
        self.editor._poll_process()
        self.assertEqual(self.editor.status_var.get(), "已停止")
        with patch("src.yys_automation.config_gui.show_diagnostic") as show:
            self.editor.diagnostic_button.invoke()
        self.assertEqual(show.call_args.args[1]["stop_reason"], "budget")
        with patch.object(self.editor, "_open_preflight") as preflight:
            show.call_args.kwargs["on_recheck"]()
        preflight.assert_called_once_with(capture_now=True)

    def test_status_from_another_process_is_ignored(self) -> None:
        now = datetime.now(timezone.utc)
        self.editor._started_at = now
        self.editor.process = Mock(pid=123)
        self.editor.status_reader = Mock()
        self.editor.status_reader.read.return_value = {"updated_at": now.isoformat(), "pid": 456}
        self.assertIsNone(self.editor._fresh_status())

    def test_inline_threshold_flow_captures_once_and_applies_only_checked_value(self) -> None:
        import cv2
        import numpy as np
        from src.yys_automation.screen import Frame
        from src.yys_automation.window import WindowInfo

        template = np.random.default_rng(45).integers(0, 256, (12, 14, 3), dtype=np.uint8)
        target = self.root_path / "victory.png"
        cv2.imwrite(str(target), template)
        image = np.zeros((50, 100, 3), dtype=np.uint8)
        image[15:27, 20:34] = template
        image[15:19, 20:34] = 0
        config = yaml.safe_load(self.config_path.read_bytes())
        config["target_image"] = "victory.png"
        config["allowed_region"] = {"left": 0, "top": 0, "width": 100, "height": 50}
        config["window"].update(reference_width=100, reference_height=50)
        config["recognition"] = {"template_scale_min": 1, "template_scale_max": 1}
        self.config_path.write_text(yaml.safe_dump(config), encoding="utf-8")
        original = yaml.safe_dump({"execution_mode": "match_any", "steps": [
            {"id": "victory", "type": "match_and_click", "image": "victory.png", "threshold": 0.99},
            {"id": "reward", "type": "match_and_click", "image": "victory.png", "threshold": 0.85},
        ]}).encode("utf-8")
        self.path.write_bytes(original)
        self.editor._load_file(self.path)
        self.editor.preflight_button.invoke()
        pane = self.editor.recognition
        self.assertEqual(self.editor.tabs.select(), str(pane))
        self.assertEqual(pane.threshold.get(), "0.99")
        data = (Frame(image, 0, 0), WindowInfo(1, "Test", 0, 0, 100, 50, 1))
        with patch("src.yys_automation.recognition_pane.capture_frame", return_value=data) as capture, \
             patch("src.yys_automation.recognition_pane.Thread", side_effect=lambda **args: Mock(start=args["target"])), \
             patch.object(pane, "after", side_effect=lambda _delay, cb, *args: cb(*args)):
            pane.capture_button.invoke()
            self.assertFalse(pane.result.current.targets[0].matched)
            pane.threshold.set("0.5")
            self.assertIn("disabled", pane.apply_button.state())
            pane.recalculate_button.invoke()
            self.assertTrue(pane.result.draft.targets[0].matched)
            self.assertEqual(len(pane.comparison.get_children()), 2)
            pane.threshold.set("0.51")
            self.assertIn("disabled", pane.apply_button.state())
            pane.threshold.set("0.5")
            pane.apply_button.invoke()
        capture.assert_called_once()
        self.assertEqual(self.editor.steps[0].threshold, 0.5)
        self.assertEqual(self.editor.steps[1].threshold, 0.85)
        self.assertEqual(self.path.read_bytes(), original)
        self.assertTrue(self.editor._save_silently())
        self.assertEqual(load_scenario(self.path).steps[0].threshold, 0.5)

    def test_inline_recognition_ignores_result_for_previously_selected_step(self) -> None:
        from queue import Queue

        pane = self.editor.recognition
        old_generation = pane.generation
        pane.busy = True
        self.editor._load_form(1)
        inbox = Queue()
        inbox.put(Mock())
        pane._poll(inbox, old_generation, True)
        self.assertEqual(pane.step.id, "second")
        self.assertIsNone(pane.result)
        self.assertIn("disabled", pane.apply_button.state())

    def test_diagnostic_renders_saved_frame_and_overlays(self) -> None:
        import tkinter as tk
        import cv2
        import numpy as np
        from src.yys_automation.diagnostics_gui import draw_diagnostic_frame, load_diagnostic_image, show_diagnostic

        folder = self.root_path / "现场"
        folder.mkdir()
        filename = "failure_preview.png"
        _, png = cv2.imencode(".png", np.zeros((50, 100, 3), dtype=np.uint8))
        (folder / filename).write_bytes(png.tobytes())
        box = {"left": 5, "top": 5, "width": 15, "height": 10}
        status = {
            "stop_reason": "no_target_timeout", "current_step": "first",
            "diagnostic": {
                "screenshot": filename, "allowed_region": {"left": 0, "top": 0, "width": 100, "height": 50},
                "observations": [{"id": "target", "box": box, "matched": False, "score": 0.6, "threshold": 0.8}],
                "screen_point": [10, 10], "origin": [0, 0], "scale": [1, 1],
            },
        }
        show_diagnostic(self.editor.root, status, folder)
        dialog = next(child for child in self.editor.root.winfo_children() if isinstance(child, tk.Toplevel))
        try:
            body = dialog.winfo_children()[0]
            canvas = next(child for child in body.winfo_children() if isinstance(child, tk.Canvas))
            frame = load_diagnostic_image(folder, status["diagnostic"])
            draw_diagnostic_frame(canvas, frame, status["diagnostic"], 600, 350)
            item_types = [canvas.type(item) for item in canvas.find_all()]
            self.assertEqual(item_types, ["image", "rectangle", "rectangle", "line", "line"])
        finally:
            dialog.destroy()

    def test_recheck_keeps_unavailable_window_identity(self) -> None:
        from src.yys_automation.preflight_gui import PreflightDialog
        from src.yys_automation.window import WindowInfo

        with patch("src.yys_automation.preflight_gui.WindowLocator") as locator:
            locator.return_value.find_all.return_value = [WindowInfo(123, "同名窗口", 0, 0, 100, 50, 789)]
            dialog = PreflightDialog(self.editor.root, load_config(self.config_path), self.editor.scenario,
                                     "first", Mock(), (123, 456))
        try:
            self.assertEqual(dialog.selected_identity(), (123, 456))
            self.assertIn("原窗口当前不可用", dialog.choice.get())
            dialog.choice.current(1)
            self.assertEqual(dialog.selected_identity(), (123, 789))
        finally:
            dialog.close()

    def test_preflight_error_does_not_spawn_process(self) -> None:
        with patch("src.yys_automation.config_gui.subprocess.Popen") as popen, \
             patch("src.yys_automation.config_gui.messagebox.showerror"):
            self.editor._start_process(self.root_path / "missing.yaml")
        popen.assert_not_called()

    def test_irrelevant_fields_are_disabled(self) -> None:
        self.assertEqual(str(self.editor.form_widgets["image"].cget("state")), "disabled")
        self.editor.form["type"].set(TYPE_LABELS["click_point"])
        self.assertEqual(str(self.editor.form_widgets["x"].cget("state")), "normal")

    def test_empty_image_shows_preview_error_without_crashing(self) -> None:
        image = self.root_path / "empty.png"
        image.touch()
        self.editor.form["type"].set(TYPE_LABELS["match_and_click"])
        self.editor.form["image"].set(str(image))
        self.editor._preview_image()
        self.assertEqual(self.editor.preview_label.cget("text"), "无法预览图片")

    def test_selected_window_identity_is_forwarded_to_child(self) -> None:
        original = self.config_path.read_bytes()
        self.editor._apply_window((123, 456), "Preview test")
        with patch("src.yys_automation.config_gui.subprocess.Popen") as popen, \
             patch.object(self.editor, "_poll_process"):
            popen.return_value.poll.return_value = None
            self.editor._start_process(self.path)
        command = popen.call_args.args[0]
        self.assertEqual(command[command.index("--window-handle") + 1], "123")
        self.assertEqual(command[command.index("--window-process-id") + 1], "456")
        self.assertEqual(self.config_path.read_bytes(), original)
        self.assertIn("disabled", self.editor.preflight_button.state())

    def test_preview_dialog_discards_results_when_window_changes(self) -> None:
        from src.yys_automation.preflight_gui import PreflightDialog
        from src.yys_automation.config import load_config

        with patch("src.yys_automation.preflight_gui.WindowLocator") as locator:
            locator.return_value.find_all.return_value = []
            dialog = PreflightDialog(self.editor.root, load_config(self.config_path), self.editor.scenario,
                                     "first", Mock())
        try:
            dialog.result = Mock()
            dialog.apply_button.configure(state="normal")
            dialog.invalidate()
            self.assertIsNone(dialog.result)
            self.assertIn("disabled", dialog.apply_button.state())
        finally:
            dialog.close()

    def test_preview_failure_restores_controls_for_retry(self) -> None:
        from src.yys_automation.preflight_gui import PreflightDialog
        from src.yys_automation.config import load_config

        with patch("src.yys_automation.preflight_gui.WindowLocator") as locator:
            locator.return_value.find_all.return_value = []
            dialog = PreflightDialog(self.editor.root, load_config(self.config_path), self.editor.scenario,
                                     "first", Mock())
        try:
            with patch("src.yys_automation.preflight_gui.threading.Thread"):
                dialog.capture()
            self.assertTrue(dialog.busy)
            self.assertIn("disabled", dialog.capture_button.state())
            dialog.dialog.after_cancel(dialog.poll_id)
            dialog.inbox.put(ValueError("window closed"))
            dialog.poll()
            self.assertFalse(dialog.busy)
            self.assertNotIn("disabled", dialog.capture_button.state())
            self.assertIn("window closed", dialog.summary.get())
            self.assertIn("disabled", dialog.apply_button.state())
        finally:
            dialog.close()

    def test_global_save_keeps_unedited_fields_and_rejects_invalid_or_stale_write(self) -> None:
        from src.yys_automation.settings_gui import save_global_settings

        raw = yaml.safe_load(self.config_path.read_bytes())
        raw["window"]["process_id"] = 1234
        raw["future_option"] = {"keep": True}
        self.config_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
        original = self.config_path.read_bytes()
        with self.assertRaisesRegex(ValueError, "exceeds reference_width"):
            save_global_settings(self.config_path, original, {"allowed_region": {"width": 9000}})
        self.assertEqual(self.config_path.read_bytes(), original)

        save_global_settings(self.config_path, original, {
            "window": {"reference_width": 1600},
            "allowed_region": {"left": 40, "width": 720},
            "scan_interval_seconds": 0.5,
        })
        saved = self.config_path.read_bytes()
        result = load_config(self.config_path)
        self.assertEqual(result.window.process_id, 1234)
        self.assertEqual(result.allowed_region, Region(40, 0, 720, 720))
        self.assertEqual(result.scan_interval_seconds, 0.5)
        self.assertEqual(yaml.safe_load(saved)["future_option"], {"keep": True})
        with self.assertRaisesRegex(ValueError, "外部修改"):
            save_global_settings(self.config_path, original, {"max_clicks": 3})
        self.assertEqual(self.config_path.read_bytes(), saved)

    def test_preview_drag_populates_dialog_and_save_refreshes_preview(self) -> None:
        import tkinter as tk
        from tkinter import ttk
        import numpy as np
        from src.yys_automation.preflight import inspect_frame
        from src.yys_automation.preflight_gui import PreflightDialog
        from src.yys_automation.screen import Frame
        from src.yys_automation.window import WindowInfo

        config = load_config(self.config_path)
        with patch("src.yys_automation.preflight_gui.WindowLocator") as locator:
            locator.return_value.find_all.return_value = []
            dialog = PreflightDialog(
                self.editor.root, config, self.editor.scenario, "first", Mock(),
                config_path=self.config_path, on_config_saved=self.editor._global_settings_saved,
            )
        try:
            frame = Frame(np.zeros((720, 1280, 3), dtype=np.uint8), 0, 0)
            window = WindowInfo(1, "Demo", 0, 0, 1280, 720, 1)
            dialog.result = inspect_frame(config, self.editor.scenario, frame, window, "first")
            dialog.image_bounds = Region(20, 30, 320, 180)
            dialog.start_selection(SimpleNamespace(x=60, y=55))
            dialog.finish_selection(SimpleNamespace(x=220, y=155))
            self.assertEqual(dialog.region, Region(160, 100, 640, 400))
            dialog.region_button.invoke()
            settings = next(child for child in dialog.dialog.winfo_children() if isinstance(child, tk.Toplevel))
            body = settings.winfo_children()[0]
            buttons = body.winfo_children()[-1]
            submit = next(child for child in buttons.winfo_children()
                          if isinstance(child, ttk.Button) and child.cget("text") == "保存全局设置")
            with patch.object(dialog, "capture") as capture:
                submit.invoke()
            capture.assert_called_once()
            self.assertEqual(load_config(self.config_path).allowed_region, Region(160, 100, 640, 400))
            self.assertEqual(dialog.config.allowed_region, Region(160, 100, 640, 400))
            self.assertEqual(dialog.dialog.grab_current(), dialog.dialog)
        finally:
            dialog.close()

    def test_match_any_settings_validate_and_save_with_inherited_template_threshold(self) -> None:
        from src.yys_automation.config import load_config

        image_path = load_config(self.config_path).target_image.resolve()
        match_any = self.root_path / "match-any.yaml"
        original = yaml.safe_dump({"execution_mode": "match_any", "steps": [
            {"id": "start", "type": "match_and_click", "image": str(image_path)},
        ]}).encode("utf-8")
        match_any.write_bytes(original)
        self.editor._load_file(match_any)
        self.assertEqual(self.editor.form["threshold"].get(), "")
        self.editor.form["wait"].set("2")
        self.assertTrue(self.editor._commit_form())
        with self.assertRaisesRegex(ValueError, "configure only one"):
            self.editor._apply_scenario_settings({"no_target_timeout_seconds": 10, "consecutive_miss_limit": 5})
        self.assertIsNone(self.editor.scenario.no_target_timeout_seconds)
        self.editor._apply_scenario_settings({
            "max_clicks": 0, "stable_frames": "3", "no_target_timeout_seconds": "25",
            "input_backend": "window_message",
        })
        self.assertTrue(self.editor._dirty)
        self.assertEqual(match_any.read_bytes(), original)
        self.assertTrue(self.editor._save_silently())
        result = load_scenario(match_any)
        self.assertEqual((result.max_clicks, result.stable_frames, result.no_target_timeout_seconds), (0, 3, 25))
        self.assertEqual(result.input_backend, "window_message")
        self.assertEqual(result.steps[0].wait_after_seconds, 2)
        self.assertIsNone(result.steps[0].threshold)


if __name__ == "__main__":
    unittest.main()
