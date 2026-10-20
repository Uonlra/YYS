from __future__ import annotations

import logging
import unittest
import tempfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.yys_automation.config import AppConfig, DurationRange, Jitter, Region, WindowConfig
from src.yys_automation.detector import Match
from src.yys_automation.scenario import Scenario, ScenarioStep, load_scenario
from src.yys_automation.screen import Frame
from src.yys_automation.workflow import WorkflowRunner


class FakeSource:
    def __init__(self, frame: Frame) -> None:
        self.frame = frame

    def grab(self) -> Frame:
        return self.frame


class FakeClicker:
    def __init__(self) -> None:
        self.points: list[tuple[int, int]] = []

    def pick_point_inside(self, box: Region, _rng: object) -> tuple[int, int]:
        return box.left, box.top

    def click(self, x: int, y: int) -> None:
        self.points.append((x, y))


class FakeStop:
    should_stop = False


def make_config(*, max_clicks: int | None = 10) -> AppConfig:
    return AppConfig(
        target_image=Path("unused.png"),
        threshold=0.86,
        allowed_region=Region(0, 0, 100, 50),
        scan_interval_seconds=0.001,
        min_click_interval_seconds=0.001,
        max_clicks=max_clicks,
        move_duration_seconds=DurationRange(0, 0),
        click_jitter_pixels=Jitter(0, 0),
        startup_delay_seconds=0,
        dry_run=False,
        log_file=Path("unused.log"),
        window=WindowConfig("test", 100, 50),
        capture_mode="window",
        template_scale_min=1,
        template_scale_max=1,
        template_scale_step=1,
    )


def make_step(step_id: str, x: int, y: int) -> ScenarioStep:
    return ScenarioStep(
        id=step_id,
        type="click_point",
        image=None,
        threshold=None,
        timeout_seconds=0.1,
        x=x,
        y=y,
        wait_after_seconds=0,
    )


class WorkflowSafetyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.logger = logging.getLogger("test_workflow")
        self.frame = Frame(np.zeros((50, 100, 3), dtype=np.uint8), 1000, 500, 2, 2)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)

    def runner(self, scenario: Scenario, *, max_clicks: int | None = 10) -> tuple[WorkflowRunner, FakeClicker]:
        clicker = FakeClicker()
        runner = WorkflowRunner(
            scenario,
            replace(make_config(max_clicks=max_clicks), log_file=Path(self.temp.name) / "automation.log"),
            FakeSource(self.frame),
            clicker,
            FakeStop(),
            self.logger,
        )
        return runner, clicker

    def test_window_allowed_region_is_mapped_to_screen_coordinates(self) -> None:
        scenario = Scenario("inside", 1, False, (make_step("click", 25, 25),))
        runner, clicker = self.runner(scenario)

        self.assertTrue(runner.run())
        self.assertEqual(clicker.points, [(1050, 550)])

    def test_click_outside_allowed_region_is_rejected(self) -> None:
        scenario = Scenario("outside", 1, False, (make_step("click", 50, 25),))
        runner, clicker = self.runner(scenario)
        runner.config = replace(runner.config, allowed_region=Region(0, 0, 50, 50))

        self.assertFalse(runner.run())
        self.assertEqual(clicker.points, [])

    def test_max_clicks_applies_to_scenario_steps(self) -> None:
        scenario = Scenario(
            "limited",
            2,
            True,
            (make_step("first", 10, 10), make_step("second", 20, 20)),
        )
        runner, clicker = self.runner(scenario, max_clicks=1)

        self.assertFalse(runner.run())
        self.assertEqual(len(clicker.points), 0)

    def test_failed_attempt_after_click_is_not_retried_by_default(self) -> None:
        scenario = Scenario(
            "no_duplicate",
            3,
            False,
            (make_step("first", 10, 10), make_step("outside", 100, 49)),
        )
        runner, clicker = self.runner(scenario)

        self.assertFalse(runner.run())
        self.assertEqual(clicker.points, [(1020, 520)])

    def test_click_exception_does_not_repeat_possibly_delivered_click(self) -> None:
        runner, clicker = self.runner(Scenario("partial", 3, False, (make_step("click", 10, 10),)))
        with patch.object(clicker, "click", side_effect=RuntimeError("delivery unknown")) as send:
            self.assertFalse(runner.run())
        self.assertEqual(send.call_count, 1)

    def test_stop_during_capture_prevents_click(self) -> None:
        runner, clicker = self.runner(Scenario("stop", 1, False, (make_step("click", 10, 10),)))
        stop = FakeStop()
        runner.stop_controller = stop

        def grab() -> Frame:
            stop.should_stop = True
            return self.frame

        with patch.object(runner.source, "grab", side_effect=grab):
            self.assertFalse(runner.run())
        self.assertEqual(clicker.points, [])

    def test_client_boundary_is_checked_even_with_large_whitelist(self) -> None:
        runner, clicker = self.runner(Scenario("client", 1, False, (make_step("click", 100, 10),)))
        runner.config = replace(runner.config, allowed_region=Region(0, 0, 1000, 1000))
        self.assertFalse(runner.run())
        self.assertEqual(clicker.points, [])

    def test_cooldown_precedes_fresh_capture(self) -> None:
        step = replace(make_step("click", 10, 10), timeout_seconds=10)
        runner, clicker = self.runner(Scenario("cooldown", 1, False, (step,)))
        runner.clicks_done = 1
        runner.last_click_at = 10
        runner.config = replace(runner.config, min_click_interval_seconds=2)
        with patch("src.yys_automation.workflow.time.monotonic", side_effect=[11, 11, 11, 11, 12, 12, 12, 12]), patch.object(
            runner, "_sleep_with_stop", return_value=True
        ) as sleep:
            self.assertTrue(runner.run())
        self.assertEqual(sleep.call_args_list[0].args, (1,))
        self.assertEqual(len(clicker.points), 1)

    def test_reward_once_clicks_three_times_and_only_observes_final_start(self) -> None:
        path = Path(__file__).resolve().parents[1] / "YYSscript/yuhun/scenario.reward-once.yaml"
        scenario = load_scenario(path)
        self.assertEqual([step.id for step in scenario.steps], ["start", "confirm", "reward", "returned_to_start"])
        self.assertEqual([step.image.name for step in scenario.steps], ["start.png", "confirm.png", "reward.png", "start.png"])
        scenario = replace(scenario, steps=tuple(replace(step, wait_after_seconds=0, next_step=None, max_attempts=1) for step in scenario.steps))
        runner, clicker = self.runner(scenario, max_clicks=3)
        runner.config = replace(runner.config, min_click_interval_seconds=0)

        with patch("src.yys_automation.workflow.TemplateDetector") as detector:
            detector.return_value.find_best.return_value = Match(0.95, Region(10, 10, 5, 5))
            self.assertTrue(runner.run())
            self.assertEqual([call.args[0] for call in detector.call_args_list], [step.image for step in scenario.steps])

        self.assertEqual(len(clicker.points), 3)
        self.assertEqual(runner.clicks_done, 3)

    def test_wait_for_image_waits_for_match_without_click_budget(self) -> None:
        step = replace(make_step("observe", 0, 0), type="wait_for_image", image=Path("unused.png"))
        runner, clicker = self.runner(Scenario("observe", 1, False, (step,)), max_clicks=0)
        with patch("src.yys_automation.workflow.TemplateDetector") as detector:
            detector.return_value.find_best.side_effect = [None, Match(0.95, Region(10, 10, 5, 5))]
            self.assertTrue(runner.run())
            self.assertEqual(detector.return_value.find_best.call_count, 2)
        self.assertEqual(clicker.points, [])
        self.assertEqual(runner.clicks_done, 0)

    def test_repeat_flow_matches_single_flow_and_repeats_whole_cycle(self) -> None:
        root = Path(__file__).resolve().parents[1] / "YYSscript/yuhun"
        once = load_scenario(root / "scenario.reward-once.yaml")
        repeated = load_scenario(root / "scenario.reward-repeat.yaml")
        self.assertEqual(once.steps, repeated.steps)
        self.assertIsNone(repeated.repeat_count)
        self.assertEqual(repeated.max_cycles, 800)
        repeated = replace(
            repeated, max_cycles=2,
            steps=tuple(replace(step, wait_after_seconds=0, next_step=None, max_attempts=1) for step in repeated.steps),
        )
        runner, clicker = self.runner(repeated, max_clicks=6)
        runner.config = replace(runner.config, min_click_interval_seconds=0)
        with patch("src.yys_automation.workflow.TemplateDetector") as detector:
            detector.return_value.find_best.return_value = Match(0.95, Region(10, 10, 5, 5))
            self.assertTrue(runner.run())
            self.assertEqual(
                [call.args[0] for call in detector.call_args_list],
                [step.image for step in repeated.steps] * 2,
            )
        self.assertEqual(runner.cycles_done, 2)
        self.assertEqual(len(clicker.points), 6)

    def test_finite_repeat_count_and_800_cycle_limit(self) -> None:
        for count in (1, 10, 800, None):
            with self.subTest(count=count):
                scenario = Scenario("finite", 1, False, (make_step("click", 10, 10),), repeat_count=count)
                runner, clicker = self.runner(scenario, max_clicks=800)
                runner.config = replace(runner.config, min_click_interval_seconds=0)
                self.assertTrue(runner.run())
                self.assertEqual(runner.cycles_done, count or 800)
                self.assertEqual(len(clicker.points), count or 800)

    def test_repeat_dry_run_counts_actions_without_sending_clicks(self) -> None:
        scenario = Scenario("dry", 1, False, (make_step("click", 10, 10),), repeat_count=2)
        runner, clicker = self.runner(scenario, max_clicks=2)
        runner.config = replace(runner.config, dry_run=True, min_click_interval_seconds=0)
        self.assertTrue(runner.run())
        self.assertEqual(runner.cycles_done, 2)
        self.assertEqual(runner.clicks_done, 2)
        self.assertEqual(clicker.points, [])

    def test_repeat_stops_on_failure_without_starting_next_cycle(self) -> None:
        scenario = Scenario("failure", 1, False, (make_step("click", 10, 10),), repeat_count=None)
        runner, _ = self.runner(scenario)
        with patch.object(runner, "_run_once", side_effect=[True, False, True]) as run_once:
            self.assertFalse(runner.run())
        self.assertEqual(run_once.call_count, 2)
        self.assertEqual(runner.cycles_done, 1)

    def test_repeat_honors_stop_between_cycles(self) -> None:
        scenario = Scenario("stop", 1, False, (make_step("click", 10, 10),), repeat_count=None)
        runner, clicker = self.runner(scenario)
        stop = FakeStop()
        runner.stop_controller = stop

        def finish_cycle() -> bool:
            stop.should_stop = True
            return True

        with patch.object(runner, "_run_once", side_effect=finish_cycle) as run_once:
            self.assertFalse(runner.run())
        self.assertEqual(run_once.call_count, 1)
        self.assertEqual(runner.cycles_done, 1)
        self.assertEqual(clicker.points, [])

    def test_repeat_preserves_click_budget_across_cycles(self) -> None:
        scenario = Scenario("budget", 1, False, (make_step("click", 10, 10),), repeat_count=None)
        runner, clicker = self.runner(scenario, max_clicks=2)
        runner.config = replace(runner.config, min_click_interval_seconds=0)
        self.assertFalse(runner.run())
        self.assertEqual(runner.cycles_done, 2)
        self.assertEqual(len(clicker.points), 2)
        self.assertEqual(runner.clicks_done, 2)

    def test_auto_budget_uses_each_tasks_click_steps_and_planned_cycles(self) -> None:
        for clicks, count, expected in ((3, 10, 30), (5, 100, 500), (3, None, 2400)):
            with self.subTest(clicks=clicks, count=count):
                steps = tuple(make_step(f"click_{i}", 10, 10) for i in range(clicks))
                scenario = Scenario("auto", 1, False, steps, repeat_count=count, max_clicks="auto")
                runner, _ = self.runner(scenario, max_clicks=1)
                self.assertEqual(runner.max_clicks, expected)
                self.assertEqual(runner.budget_source, "scenario.auto")

    def test_explicit_task_budget_overrides_global_default(self) -> None:
        scenario = Scenario("override", 1, False, (make_step("click", 10, 10),), max_clicks=2)
        runner, clicker = self.runner(scenario, max_clicks=0)
        self.assertTrue(runner.run())
        self.assertEqual(runner.max_clicks, 2)
        self.assertEqual(runner.budget_source, "scenario.max_clicks")
        self.assertEqual(len(clicker.points), 1)

    def test_zero_task_budget_stops_before_click(self) -> None:
        scenario = Scenario("disabled", 1, False, (make_step("click", 10, 10),), max_clicks=0)
        runner, clicker = self.runner(scenario)
        self.assertFalse(runner.run())
        self.assertEqual(clicker.points, [])

    def test_auto_budget_counts_failed_clicks_without_granting_retry_allowance(self) -> None:
        scenario = Scenario("retry", 3, True, (make_step("click", 10, 10),), max_clicks="auto")
        runner, clicker = self.runner(scenario)
        runner.config = replace(runner.config, min_click_interval_seconds=0)
        with patch.object(clicker, "click", side_effect=RuntimeError("delivery unknown")) as send:
            self.assertFalse(runner.run())
        self.assertEqual(send.call_count, 1)
        self.assertEqual(runner.clicks_done, 1)
        self.assertEqual(runner.max_clicks, 1)

    def test_auto_budget_excludes_wait_steps_and_logs_source(self) -> None:
        step = replace(make_step("wait", 0, 0), type="wait", timeout_seconds=0.001)
        scenario = Scenario("observe", 1, False, (step,), max_clicks="auto")
        runner, clicker = self.runner(scenario)
        with self.assertLogs(self.logger, level="INFO") as logs:
            self.assertTrue(runner.run())
        self.assertTrue(any("max_clicks=0 source=scenario.auto" in entry for entry in logs.output))
        self.assertEqual(clicker.points, [])

    def test_wait_for_image_times_out_when_target_never_appears(self) -> None:
        step = replace(make_step("observe", 0, 0), type="wait_for_image", image=Path("unused.png"), timeout_seconds=0.01)
        runner, clicker = self.runner(Scenario("timeout", 1, False, (step,)))
        with patch("src.yys_automation.workflow.TemplateDetector") as detector:
            detector.return_value.find_best.return_value = None
            detector.return_value.last_score = 0.1
            detector.return_value.threshold = 0.86
            detector.return_value.last_location = (0, 0)
            detector.return_value.last_scale = 1.0
            self.assertFalse(runner.run())
        self.assertEqual(clicker.points, [])

    def test_wait_for_image_honors_stop_during_capture(self) -> None:
        step = replace(make_step("observe", 0, 0), type="wait_for_image", image=Path("unused.png"))
        runner, clicker = self.runner(Scenario("stop", 1, False, (step,)))
        stop = FakeStop()
        runner.stop_controller = stop

        def grab() -> Frame:
            stop.should_stop = True
            return self.frame

        with patch.object(runner.source, "grab", side_effect=grab), patch(
            "src.yys_automation.workflow.TemplateDetector"
        ) as detector:
            detector.return_value.find_best.return_value = Match(0.95, Region(10, 10, 5, 5))
            self.assertFalse(runner.run())
        self.assertEqual(clicker.points, [])


if __name__ == "__main__":
    unittest.main()
