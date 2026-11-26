from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import yaml

from run import main, parse_args
from src.yys_automation.config import load_config


class CliTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.config_path = Path(self.temp.name) / "config.yaml"
        self.stdout = io.StringIO()
        self.stderr = io.StringIO()
        self.enterContext(contextlib.redirect_stdout(self.stdout))
        self.enterContext(contextlib.redirect_stderr(self.stderr))

    def invoke(self, *args: str) -> int:
        return main(["--config", str(self.config_path), *args])

    def test_init_config_works_outside_project_and_defaults_to_dry_run(self) -> None:
        self.assertEqual(self.invoke("--init-config"), 0)
        config = load_config(self.config_path)
        self.assertTrue(config.dry_run)
        self.assertTrue(config.target_image.is_file())
        self.assertEqual(config.log_file.parent, self.config_path.parent / "logs")

    def test_init_never_overwrites_existing_content(self) -> None:
        self.config_path.write_text("personal settings", encoding="utf-8")
        self.assertEqual(self.invoke("--init-config"), 2)
        self.assertEqual(self.config_path.read_text(encoding="utf-8"), "personal settings")
        self.assertIn("not overwritten", self.stderr.getvalue())

    def test_init_missing_parent_reports_error(self) -> None:
        self.config_path = self.config_path.parent / "missing" / "config.yaml"
        self.assertEqual(self.invoke("--init-config"), 2)
        self.assertIn("Cannot create config", self.stderr.getvalue())

    def test_init_supports_config_on_another_drive(self) -> None:
        with patch("run.os.path.relpath", side_effect=ValueError("different drives")):
            self.assertEqual(self.invoke("--init-config"), 0)
        config = load_config(self.config_path)
        self.assertTrue(config.target_image.is_absolute())
        self.assertTrue(config.target_image.is_file())

    def test_missing_config_reports_recovery_command(self) -> None:
        self.assertEqual(self.invoke("--validate-config"), 2)
        self.assertIn("--init-config", self.stderr.getvalue())

    def test_validate_config_does_not_start_automation(self) -> None:
        self.assertEqual(self.invoke("--init-config"), 0)
        with patch("run.run") as run:
            self.assertEqual(self.invoke("--validate-config"), 0)
        run.assert_not_called()
        self.assertIn("Config valid", self.stdout.getvalue())
        self.assertFalse((self.config_path.parent / "logs").exists())

    def test_onboarding_example_is_valid_and_limited_to_one_click(self) -> None:
        from src.yys_automation.scenario import load_scenario, validate_scenario

        root = Path(__file__).resolve().parents[1]
        config = load_config(root / "config.example.yaml")
        path = root / "scenario.example.yaml"
        self.assertEqual(validate_scenario(path, config), [])
        scenario = load_scenario(path)
        self.assertEqual(scenario.click_budget(config)[0], 1)
        self.assertEqual(scenario.click_attempts_per_cycle, 1)

    def test_validate_bad_yaml_has_no_traceback(self) -> None:
        self.config_path.write_text("[broken", encoding="utf-8")
        self.assertEqual(self.invoke("--validate-config"), 2)
        self.assertIn("Invalid config", self.stderr.getvalue())
        self.assertNotIn("Traceback", self.stderr.getvalue())

    def test_validate_missing_target_reports_error(self) -> None:
        self.invoke("--init-config")
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        data["target_image"] = "missing.png"
        self.config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        self.assertEqual(self.invoke("--validate-config"), 2)
        self.assertIn("Target image not found", self.stderr.getvalue())

    def test_dry_run_overrides_real_click_config_without_writing_file(self) -> None:
        self.invoke("--init-config")
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        data["dry_run"] = False
        self.config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        before = self.config_path.read_bytes()
        with patch("run.run", return_value=0) as run:
            self.assertEqual(self.invoke("--dry-run"), 0)
        self.assertTrue(run.call_args.args[0].dry_run)
        self.assertEqual(before, self.config_path.read_bytes())

    def test_dry_run_reaches_gui(self) -> None:
        self.invoke("--init-config")
        with patch("src.yys_automation.config_gui.launch_gui") as launch:
            self.assertEqual(self.invoke("--dry-run", "--gui", "test.yaml"), 0)
        launch.assert_called_once_with(Path("test.yaml"), self.config_path, dry_run=True)

    def test_resume_gui_uses_shipped_scenario_as_fallback(self) -> None:
        self.invoke("--init-config")
        with patch("src.yys_automation.config_gui.launch_gui") as launch:
            self.assertEqual(self.invoke("--resume-gui", "--dry-run"), 0)
        scenario, config = launch.call_args.args
        self.assertEqual(scenario.name, "scenario.match-any.yaml")
        self.assertTrue(scenario.is_file())
        self.assertEqual(config, self.config_path)
        self.assertEqual(launch.call_args.kwargs, {"dry_run": True, "restore_recent": True})

    def test_gui_passes_dry_run_to_child_process(self) -> None:
        from src.yys_automation.config_gui import ScenarioEditor

        self.invoke("--init-config")
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        data["dry_run"] = False
        self.config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        for dry_run in (True, False):
            with self.subTest(dry_run=dry_run):
                editor = ScenarioEditor(config_path=self.config_path, dry_run=dry_run)
                self.addCleanup(editor.root.destroy)
                editor.root.withdraw()
                editor.dry_run_var.set(dry_run)
                editor._poll_status = Mock()
                editor._poll_process = Mock()
                with patch("src.yys_automation.config_gui.subprocess.Popen") as popen:
                    editor._start_process(Path(__file__).resolve().parents[1] / "scenario.example.yaml")
                self.assertEqual("--dry-run" in popen.call_args.args[0], dry_run)
                editor._remove_output()

    def test_scenario_receives_dry_run_override(self) -> None:
        from src.yys_automation.scenario import Scenario

        self.invoke("--init-config")
        data = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))
        data["dry_run"] = False
        self.config_path.write_text(yaml.safe_dump(data), encoding="utf-8")
        with patch("src.yys_automation.scenario.validate_scenario", return_value=[]), \
             patch("src.yys_automation.scenario.load_scenario", return_value=Scenario("test", 1, False, ())), \
             patch("src.yys_automation.safety.StopController"), \
             patch("src.yys_automation.window_screen.WindowScreenCapture"), \
             patch("src.yys_automation.window_clicker.WindowMessageClicker"), \
             patch("src.yys_automation.workflow.WorkflowRunner") as runner, \
             patch("run.setup_logging"):
            runner.return_value.run.return_value = True
            self.assertEqual(self.invoke("--dry-run", "--scenario", "test.yaml"), 0)
        self.assertTrue(runner.call_args.args[1].dry_run)
        self.assertFalse(load_config(self.config_path).dry_run)

    def test_conflicting_actions_are_rejected(self) -> None:
        actions = [
            ["--init-config"], ["--validate-config"], ["--probe-window"],
            ["--capture-window", "capture.png"], ["--diagnose-match"],
            ["--validate-scenario", "flow.yaml"], ["--scenario", "flow.yaml"],
            ["--gui", "flow.yaml"], ["--resume-gui"],
        ]
        for index, first in enumerate(actions):
            for second in actions[index + 1:]:
                with self.subTest(first=first, second=second):
                    with self.assertRaises(SystemExit) as error:
                        parse_args(first + second)
                    self.assertEqual(error.exception.code, 2)

    def test_window_identity_flags_require_positive_pair(self) -> None:
        for values in (["--window-handle", "123"], ["--window-process-id", "456"],
                       ["--window-handle", "0", "--window-process-id", "456"]):
            with self.subTest(values=values), self.assertRaises(SystemExit):
                parse_args(values)

    def test_window_override_reaches_runtime_without_rewriting_config(self) -> None:
        self.invoke("--init-config")
        before = self.config_path.read_bytes()
        with patch("run.run", return_value=0) as run:
            self.assertEqual(self.invoke("--window-handle", "123", "--window-process-id", "456"), 0)
        window = run.call_args.args[0].window
        self.assertEqual((window.handle, window.process_id, window.title_contains), (123, 456, ""))
        self.assertEqual(before, self.config_path.read_bytes())


if __name__ == "__main__":
    unittest.main()
