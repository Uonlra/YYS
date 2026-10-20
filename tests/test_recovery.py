from __future__ import annotations

import logging
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

import numpy as np

from src.yys_automation.config import Region
from src.yys_automation.detector import Match
from src.yys_automation.scenario import Scenario, ScenarioStep
from src.yys_automation.screen import Frame
from src.yys_automation.workflow import WorkflowRunner
from test_workflow import FakeClicker, FakeStop, make_config, make_step


class Clock:
    now = 100.0

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


class StateSource:
    def __init__(self, states: list[int]) -> None:
        self.states = iter(states)
        self.current = states[-1]

    def grab(self) -> Frame:
        self.current = next(self.states, self.current)
        return Frame(np.full((50, 100, 3), self.current, dtype=np.uint8), 0, 0)


class StateDetector:
    def __init__(self, path: Path, threshold: float, *_scales: float) -> None:
        self.value = {"start": 1, "confirm": 2, "reward": 3}[path.stem]
        self.threshold = threshold
        self.last_score = 0.0
        self.last_location = (0, 0)
        self.last_scale = 1.0

    def find_best(self, image: np.ndarray) -> Match | None:
        value = int(image[0, 0, 0])
        self.last_score = 0.95 if value in (self.value, 9) else 0.1
        return Match(self.last_score, Region(10, 10, 5, 5)) if self.last_score >= self.threshold else None


class RecoveryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.clock = Clock()
        self.addCleanup(patch.stopall)
        patch("src.yys_automation.workflow.time.monotonic", self.clock.monotonic).start()
        patch("src.yys_automation.workflow.time.sleep", self.clock.sleep).start()
        patch("src.yys_automation.workflow.TemplateDetector", StateDetector).start()
        self.start = replace(
            make_step("start", 10, 10), type="match_and_click", image=Path("start.png"),
            max_attempts=3, next_step="confirm", timeout_seconds=0.1,
            response_timeout_seconds=0.02, recover_to=("confirm", "reward"),
        )
        self.confirm = replace(
            self.start, id="confirm", image=Path("confirm.png"), next_step="reward", recover_to=("reward",),
        )
        self.reward = replace(
            self.start, id="reward", image=Path("reward.png"), next_step="returned", recover_to=("returned",),
        )
        self.returned = replace(
            self.start, id="returned", type="wait_for_image", image=Path("start.png"),
            next_step=None, max_attempts=1, recover_to=(),
        )

    def runner(self, states: list[int], steps: tuple[ScenarioStep, ...] | None = None) -> WorkflowRunner:
        scenario = Scenario(
            "recover", 1, False, steps or (self.start, self.confirm, self.reward, self.returned),
            max_clicks="auto", recovery_scans=2, recovery_interval_seconds=0.01,
        )
        config = replace(
            make_config(), log_file=Path(self.temp.name) / "automation.log",
            scan_interval_seconds=0.01, min_click_interval_seconds=0.01,
        )
        return WorkflowRunner(scenario, config, StateSource(states), FakeClicker(), FakeStop(), logging.getLogger("recovery_tests"))

    def test_successful_cycle_confirms_each_transition_and_only_clicks_three_times(self) -> None:
        runner = self.runner([1, 2, 2, 3, 3, 1, 1])
        self.assertTrue(runner.run())
        self.assertEqual(runner.clicks_done, 3)
        self.assertEqual(runner.cycles_done, 1)
        self.assertEqual(runner.max_clicks, 9)

    def test_unresponsive_button_gets_at_most_three_fresh_click_attempts(self) -> None:
        runner = self.runner([1])
        self.assertFalse(runner._run_step(self.start))
        self.assertEqual(runner.clicks_done, 3)
        self.assertEqual(runner.failure_reason, "attempts_exhausted")

    def test_button_disappears_during_battle_no_more_clicks_even_if_it_returns(self) -> None:
        runner = self.runner([1, 0, 0, 1])
        self.assertFalse(runner._run_step(self.start))
        self.assertEqual(runner.clicks_done, 1)
        self.assertEqual(runner.failure_reason, "timeout")

    def test_long_transition_wait_is_not_short_click_response_timeout(self) -> None:
        runner = self.runner([1] + [0] * 5 + [2])
        self.assertTrue(runner._run_step(self.start))
        self.assertEqual(runner.clicks_done, 1)
        self.assertGreater(self.clock.now, 100.02)

    def test_possibly_delivered_click_is_observed_before_retry(self) -> None:
        runner = self.runner([1, 2])
        with patch.object(runner.clicker, "click", side_effect=RuntimeError("unknown delivery")) as send:
            self.assertTrue(runner._run_step(self.start))
        self.assertEqual(send.call_count, 1)
        self.assertEqual(runner.clicks_done, 1)

    def test_bounds_budget_stop_and_ambiguous_states_never_retry(self) -> None:
        for condition in ("bounds", "budget", "stop", "ambiguous"):
            with self.subTest(condition=condition):
                runner = self.runner([9 if condition == "ambiguous" else 1])
                if condition == "bounds":
                    runner.config = replace(runner.config, allowed_region=Region(70, 20, 10, 10))
                elif condition == "budget":
                    runner.max_clicks = 0
                elif condition == "stop":
                    runner.stop_controller = FakeStop()
                    runner.stop_controller.should_stop = True
                self.assertFalse(runner._run_step(self.start))
                self.assertEqual(runner.clicks_done, 0)

    def test_recovery_only_scans_twice_and_never_clicks(self) -> None:
        runner = self.runner([0])
        with patch.object(runner.source, "grab", wraps=runner.source.grab) as grab:
            self.assertIsNone(runner._recover(self.start))
        self.assertEqual(grab.call_count, 2)
        self.assertEqual(runner.clicks_done, 0)

    def test_second_scan_recovers_to_reward_but_not_back_to_start(self) -> None:
        runner = self.runner([0, 3])
        self.assertEqual(runner._recover(self.confirm), 2)
        runner.source = StateSource([1])
        self.assertIsNone(runner._recover(self.confirm))
        self.assertEqual(runner.clicks_done, 0)

    def test_ambiguous_recovery_is_rejected(self) -> None:
        runner = self.runner([9])
        self.assertIsNone(runner._recover(self.start))
        self.assertEqual(runner.failure_reason, "ambiguous")

    def test_recovery_entry_caps_action_at_two_attempts(self) -> None:
        runner = self.runner([2])
        runner._recovery_entry = True
        self.assertFalse(runner._run_step(self.confirm))
        self.assertEqual(runner.clicks_done, 2)

    def test_forward_recovery_runs_candidate_without_repeating_start(self) -> None:
        runner = self.runner([0])
        visited = []

        def run_step(step: ScenarioStep) -> bool:
            visited.append((step.id, runner._recovery_entry))
            runner.failure_reason = "timeout"
            return step.id != "start"

        with patch.object(runner, "_run_step", side_effect=run_step), patch.object(
            runner, "_recover", return_value=2
        ), patch.object(runner, "_save_failure"):
            self.assertTrue(runner._run_once())
        self.assertEqual(visited, [("start", False), ("reward", True), ("returned", False)])

    def test_failure_screenshots_are_bounded_and_fallback_uses_last_frame(self) -> None:
        runner = self.runner([1])
        runner.last_frame = runner.source.grab()
        runner.failure_reason = "timeout"
        with patch.object(runner.source, "grab", side_effect=RuntimeError("window gone")):
            for _ in range(22):
                runner._save_failure(self.start)
        files = list((Path(self.temp.name) / "failures").glob("failure_*.png"))
        self.assertEqual(len(files), 20)

    def test_screenshot_write_error_does_not_prevent_stopping(self) -> None:
        runner = self.runner([1])
        with patch("src.yys_automation.workflow.cv2.imwrite", return_value=False):
            runner._save_failure(self.start)
        self.assertEqual(list((Path(self.temp.name) / "failures").glob("*.png")), [])

    def test_whole_cycle_retry_cannot_reset_step_limit_or_recovery_scan_limit(self) -> None:
        runner = self.runner([1])
        runner.scenario = replace(runner.scenario, max_retries=3, retry_after_clicks=True)
        runner.max_clicks = 100
        with patch.object(runner, "_recover", wraps=runner._recover) as recover:
            self.assertFalse(runner.run())
        self.assertEqual(runner.clicks_done, 3)
        self.assertEqual(recover.call_count, 1)

    def test_failsafe_is_terminal_and_never_enters_recovery(self) -> None:
        from pyautogui import FailSafeException

        runner = self.runner([1])
        with patch.object(runner.clicker, "click", side_effect=FailSafeException("stop")) as click, patch.object(
            runner, "_recover"
        ) as recover:
            self.assertFalse(runner.run())
        self.assertEqual(click.call_count, 1)
        recover.assert_not_called()
        self.assertEqual(runner.failure_reason, "failsafe")

    def test_recovery_rechecks_target_on_fresh_frame_before_clicking(self) -> None:
        runner = self.runner([3, 0])
        self.assertEqual(runner._recover(self.confirm), 2)
        runner._recovery_entry = True
        self.assertFalse(runner._run_step(self.reward))
        self.assertEqual(runner.clicks_done, 0)

    def test_stop_during_recovery_scan_prevents_resume(self) -> None:
        runner = self.runner([3])
        stop = FakeStop()
        runner.stop_controller = stop
        original_grab = runner.source.grab

        def grab() -> Frame:
            stop.should_stop = True
            return original_grab()

        with patch.object(runner.source, "grab", side_effect=grab):
            self.assertIsNone(runner._recover(self.confirm))
        self.assertEqual(runner.clicks_done, 0)

    def test_failure_screenshot_is_not_attempted_for_user_stop(self) -> None:
        runner = self.runner([1])
        stop = FakeStop()
        runner.stop_controller = stop

        def stopped_step(_step: ScenarioStep) -> bool:
            stop.should_stop = True
            return False

        with patch.object(runner, "_run_step", side_effect=stopped_step), patch.object(runner, "_save_failure") as save:
            self.assertFalse(runner._run_once())
        save.assert_not_called()

    def test_cycle_start_reserves_budget_for_all_authorized_attempts(self) -> None:
        runner = self.runner([1])
        runner.max_clicks = 8
        with patch.object(runner.source, "grab") as capture:
            self.assertFalse(runner.run())
        capture.assert_not_called()
        self.assertEqual(runner.clicks_done, 0)


if __name__ == "__main__":
    unittest.main()
