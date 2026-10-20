from __future__ import annotations

import logging
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.yys_automation.config import AppConfig, DurationRange, Jitter, Region, WindowConfig
from src.yys_automation.scenario import Scenario, ScenarioStep
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

    def runner(self, scenario: Scenario, *, max_clicks: int | None = 10) -> tuple[WorkflowRunner, FakeClicker]:
        clicker = FakeClicker()
        runner = WorkflowRunner(
            scenario,
            make_config(max_clicks=max_clicks),
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
        self.assertEqual(len(clicker.points), 1)

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


if __name__ == "__main__":
    unittest.main()
