from __future__ import annotations

import logging
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from src.yys_automation.config import Region
from src.yys_automation.detector import Match
from src.yys_automation.clicker import HumanLikeClicker
from src.yys_automation.scenario import Scenario, load_scenario
from src.yys_automation.workflow import WorkflowRunner
from run import main
from test_recovery import Clock, StateDetector, StateSource
from test_workflow import FakeClicker, FakeStop, make_config, make_step


class MatchAnyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.addCleanup(patch.stopall)
        patch("src.yys_automation.workflow.time.monotonic", self.clock.monotonic).start()
        patch("src.yys_automation.workflow.time.sleep", self.clock.sleep).start()
        patch("src.yys_automation.workflow.TemplateDetector", StateDetector).start()

    def runner(self, states: list[int], limit: int = 3) -> WorkflowRunner:
        steps = tuple(replace(make_step(name, 0, 0), type="match_and_click", image=Path(f"{name}.png"))
                      for name in ("start", "confirm", "reward"))
        scenario = Scenario("any", 1, False, steps, execution_mode="match_any", max_clicks=limit)
        config = replace(make_config(), log_file=Path(self.temp.name) / "automation.log",
                         min_click_interval_seconds=0.03, scan_interval_seconds=0.01)
        return WorkflowRunner(scenario, config, StateSource(states), FakeClicker(), FakeStop(), logging.getLogger("match_any_tests"))

    def test_arbitrary_order_clicks_without_cycle_count(self) -> None:
        runner = self.runner([3, 1, 2])
        with self.assertLogs(runner.logger, level="INFO") as logs:
            self.assertTrue(runner.run())
        targets = [entry.split("target=")[1].split()[0] for entry in logs.output if "Match-any target=" in entry]
        self.assertEqual(targets, ["reward", "start", "confirm"])
        self.assertEqual(runner.clicks_done, 3)
        self.assertEqual(runner.cycles_done, 0)

    def test_same_image_can_be_clicked_again_after_cooldown(self) -> None:
        runner = self.runner([1])
        times = []
        with patch.object(runner.clicker, "click", side_effect=lambda *_point: times.append(self.clock.now)):
            self.assertTrue(runner.run())
        self.assertEqual(len(times), 3)
        self.assertTrue(all(b - a >= 0.029 for a, b in zip(times, times[1:])))

    def test_missing_targets_keep_waiting_without_click(self) -> None:
        runner = self.runner([0, 0, 2], limit=1)
        with patch.object(runner.source, "grab", wraps=runner.source.grab) as capture:
            self.assertTrue(runner.run())
        self.assertEqual(capture.call_count, 3)
        self.assertEqual(runner.clicks_done, 1)

    def test_highest_score_wins_and_only_one_click_per_frame(self) -> None:
        runner = self.runner([9], limit=1)

        class ScoredDetector(StateDetector):
            def find_best(self, image):
                return Match({1: 0.87, 2: 0.99, 3: 0.91}[self.value], Region(10, 10, 5, 5))

        with patch("src.yys_automation.workflow.TemplateDetector", ScoredDetector), self.assertLogs(runner.logger, level="INFO") as logs:
            self.assertTrue(runner.run())
        self.assertTrue(any("Match-any target=confirm" in entry for entry in logs.output))
        self.assertEqual(runner.clicks_done, 1)

    def test_dry_run_counts_and_obeys_limit_without_real_clicks(self) -> None:
        runner = self.runner([3], limit=2)
        runner.config = replace(runner.config, dry_run=True)
        self.assertTrue(runner.run())
        self.assertEqual(runner.clicks_done, 2)
        self.assertEqual(runner.clicker.points, [])

    def test_stop_after_capture_prevents_click(self) -> None:
        runner = self.runner([1])
        grab = runner.source.grab

        def stopped_capture():
            runner.stop_controller.should_stop = True
            return grab()

        with patch.object(runner.source, "grab", side_effect=stopped_capture):
            self.assertFalse(runner.run())
        self.assertEqual(runner.clicks_done, 0)

    def test_bounds_and_click_failure_stop_without_recovery(self) -> None:
        for failure in ("bounds", "click"):
            with self.subTest(failure=failure):
                runner = self.runner([1])
                if failure == "bounds":
                    runner.config = replace(runner.config, allowed_region=Region(60, 0, 10, 10))
                with patch.object(runner.clicker, "click", side_effect=RuntimeError("delivery unknown")) as click, patch.object(
                    runner, "_recover"
                ) as recover:
                    self.assertFalse(runner.run())
                self.assertEqual(click.call_count, 0 if failure == "bounds" else 1)
                recover.assert_not_called()

    def test_zero_budget_exits_without_capture(self) -> None:
        runner = self.runner([1], limit=0)
        with patch.object(runner.source, "grab") as capture:
            self.assertTrue(runner.run())
        capture.assert_not_called()

    def test_capture_exception_stops_and_saves_diagnostic(self) -> None:
        runner = self.runner([1])
        with patch.object(runner.source, "grab", side_effect=RuntimeError("window closed")), patch.object(
            runner, "_save_failure"
        ) as save:
            self.assertFalse(runner.run())
        save.assert_called_once()
        self.assertEqual(runner.clicks_done, 0)

    def test_shipped_config_is_unordered_and_bounded(self) -> None:
        scenario = load_scenario(Path(__file__).resolve().parents[1] / "YYSscript/yuhun/scenario.match-any.yaml")
        self.assertEqual(scenario.execution_mode, "match_any")
        self.assertEqual(scenario.input_backend, "window_message")
        self.assertEqual(scenario.max_clicks, 2400)
        self.assertEqual([step.image.stem for step in scenario.steps], ["start", "confirm", "reward"])

    def test_match_any_cli_selects_configured_input_backend(self) -> None:
        from dataclasses import replace
        from test_workflow import make_config

        for backend, physical, message in (("physical_mouse", True, False), ("window_message", False, True)):
            with self.subTest(backend=backend):
                scenario = Scenario("any", 1, False, (), execution_mode="match_any", input_backend=backend)
                with patch("sys.argv", ["run.py", "--config", "config.yaml", "--scenario", "any.yaml"]), \
                     patch("src.yys_automation.scenario.validate_scenario", return_value=[]), \
                     patch("src.yys_automation.scenario.load_scenario", return_value=scenario), \
                     patch("src.yys_automation.safety.StopController"), \
                     patch("src.yys_automation.window_screen.WindowScreenCapture"), \
                     patch("src.yys_automation.clicker.HumanLikeClicker") as physical_clicker, \
                     patch("src.yys_automation.window_clicker.WindowMessageClicker") as message_clicker, \
                     patch("src.yys_automation.workflow.WorkflowRunner") as runner, \
                     patch("run.setup_logging"), patch("run.load_config") as load_config:
                    runner.return_value.run.return_value = True
                    load_config.return_value = replace(make_config(), capture_mode="window")
                    self.assertEqual(main(), 0)
                self.assertEqual(physical_clicker.call_count == 1, physical)
                self.assertEqual(message_clicker.call_count == 1, message)


if __name__ == "__main__":
    unittest.main()
