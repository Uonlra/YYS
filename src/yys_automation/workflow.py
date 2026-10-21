from __future__ import annotations

import logging
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Protocol

import cv2

from src.yys_automation.config import AppConfig, Region
from src.yys_automation.detector import TemplateDetector
from src.yys_automation.scenario import Scenario, ScenarioStep
from src.yys_automation.screen import Frame


class FrameSource(Protocol):
    def grab(self) -> Frame:
        ...


class Clicker(Protocol):
    def pick_point_inside(self, box: Region, rng: random.Random) -> tuple[int, int]:
        ...

    def click(self, x: int, y: int) -> None:
        ...


class StateConfirmation:
    """Consecutive identical observations, including unknown and conflicting frames."""

    def __init__(self, frames: int) -> None:
        self.frames = frames
        self.last: tuple[str, ...] | None = None
        self.count = 0

    def update(self, visible: list[str]) -> bool:
        key = tuple(visible)
        self.count = self.count + 1 if key == self.last else 1
        self.last = key
        return self.count >= self.frames

    def reset(self) -> None:
        self.last = None
        self.count = 0


class WorkflowRunner:
    def __init__(
        self,
        scenario: Scenario,
        config: AppConfig,
        source: FrameSource,
        clicker: Clicker,
        stop_controller: object,
        logger: logging.Logger,
    ) -> None:
        self.scenario = scenario
        self.config = config
        self.source = source
        self.clicker = clicker
        self.stop_controller = stop_controller
        self.logger = logger
        self.clicks_done = 0
        self.last_click_at = 0.0
        self._attempt_clicked = False
        self.cycles_done = 0
        self.max_clicks, self.budget_source = scenario.click_budget(config)
        self.failure_reason = ""
        self.last_frame: Frame | None = None
        self._detectors: dict[str, TemplateDetector] = {}
        self._recovery_entry = False
        self._cycle_actions: set[str] = set()
        self._resume_index: int | None = None

    def run(self) -> bool:
        if self.scenario.execution_mode == "match_any":
            return self._run_match_any()
        cycle_limit = self.scenario.cycle_limit
        clicks_per_cycle = self.scenario.clicks_per_cycle
        required_clicks = self.scenario.click_attempts_per_cycle
        self.logger.info(
            "Scenario budget: clicks_per_cycle=%d cycles=%d max_clicks=%s source=%s dry_run=%s max_attempts_per_cycle=%d",
            clicks_per_cycle, cycle_limit,
            self.max_clicks if self.max_clicks is not None else "unlimited",
            self.budget_source, self.config.dry_run, self.scenario.click_attempts_per_cycle,
        )
        for cycle in range(1, cycle_limit + 1):
            if self._should_stop():
                return False
            if self.max_clicks is not None and self.clicks_done + required_clicks > self.max_clicks:
                self.logger.warning(
                    "Scenario stopped before cycle %d: insufficient click budget "
                    "done=%d max=%d required=%d completed_cycles=%d",
                    cycle, self.clicks_done, self.max_clicks, required_clicks, self.cycles_done,
                )
                return False
            self.logger.info("Scenario cycle %d/%d: %s", cycle, cycle_limit, self.scenario.name)
            if not self._run_cycle():
                self.logger.error("Scenario stopped: completed_cycles=%d clicks=%d", self.cycles_done, self.clicks_done)
                return False
            self.cycles_done += 1
            self.logger.info("Scenario cycle completed: %d clicks=%d", self.cycles_done, self.clicks_done)
        if self.scenario.repeat_count is None:
            self.logger.info("Scenario reached safety cycle limit: %d", self.scenario.max_cycles)
        self.logger.info("Scenario completed: %s cycles=%d", self.scenario.name, self.cycles_done)
        return True

    def _run_match_any(self) -> bool:
        self.logger.info("Match-any starting: targets=%s max_clicks=%s source=%s dry_run=%s; no step order or cycle count",
                         [step.id for step in self.scenario.steps], self.max_clicks,
                         self.budget_source, self.config.dry_run)
        active = self.scenario.steps[0]
        last_diagnostic = float("-inf")
        try:
            detectors = [(step, self._detector(step)) for step in self.scenario.steps]
            while not self._should_stop():
                if self.max_clicks is not None and self.clicks_done >= self.max_clicks:
                    self.logger.info("Match-any click limit reached: clicks=%d max=%d", self.clicks_done, self.max_clicks)
                    return True
                if self.clicks_done:
                    remaining = self.config.min_click_interval_seconds - (time.monotonic() - self.last_click_at)
                    if remaining > 0:
                        if not self._sleep_with_stop(remaining):
                            return False
                        continue
                frame = self.source.grab()
                self.last_frame = frame
                matches = []
                for step, detector in detectors:
                    active = step
                    match = detector.find_best(frame.image)
                    if match is not None:
                        matches.append((step, match))
                if self._should_stop():
                    return False
                if not matches:
                    if time.monotonic() - last_diagnostic >= 5:
                        self.logger.info("Match-any waiting: no target found; scores=%s",
                                         {step.id: round(detector.last_score, 4) for step, detector in detectors})
                        last_diagnostic = time.monotonic()
                    if not self._sleep_with_stop(self.config.scan_interval_seconds):
                        return False
                    continue
                active, match = max(matches, key=lambda item: item[1].score)
                box = frame.to_screen_region(match.box)
                point = self.clicker.pick_point_inside(box, random.Random())
                self.logger.info("Match-any target=%s score=%.4f point=(%d,%d)", active.id, match.score, *point)
                if not self._perform_click_if_allowed(active, frame, *point):
                    if not self._should_stop():
                        self._save_failure(active)
                    return False
                self.logger.info("Match-any action count=%d", self.clicks_done)
                if not self._sleep_with_stop(self.config.scan_interval_seconds):
                    return False
        except Exception:
            self.failure_reason = "error"
            self.logger.exception("Match-any failed: target=%s", active.id)
            if not self._should_stop():
                self._save_failure(active)
            return False
        self.logger.info("Match-any stopped by user: clicks=%d", self.clicks_done)
        return False

    def _run_cycle(self) -> bool:
        for attempt in range(1, self.scenario.max_retries + 1):
            self._attempt_clicked = False
            self.logger.info(
                "Scenario attempt %d/%d: %s",
                attempt,
                self.scenario.max_retries,
                self.scenario.name,
            )
            if self._run_once():
                return True
            if self._should_stop():
                break
            if any(step.next_step or step.recover_to for step in self.scenario.steps):
                self.logger.error("State-confirmed scenario stopped after bounded step recovery; no whole-cycle replay")
                break
            if self.failure_reason in {"bounds", "budget", "ambiguous", "error", "failsafe", "phase"}:
                break
            if self._attempt_clicked and not self.scenario.retry_after_clicks:
                self.logger.error("Scenario retry stopped after a click: %s", self.scenario.name)
                break
            self.logger.warning("Scenario attempt failed: %d/%d", attempt, self.scenario.max_retries)
        self.logger.error("Scenario failed: %s", self.scenario.name)
        return False

    def _run_once(self) -> bool:
        index = 0
        self._recovery_entry = False
        self._cycle_actions.clear()
        while index < len(self.scenario.steps):
            step = self.scenario.steps[index]
            if self._should_stop():
                return False
            self.failure_reason = ""
            self._resume_index = None
            self.logger.info("Step started: %s type=%s", step.id, step.type)
            try:
                success = self._run_step(step)
            except Exception as exc:
                self.failure_reason = "error"
                self.logger.exception("Step %s unexpected error: %s", step.id, exc)
                success = False
            if not success:
                self.logger.error("Step failed: %s", step.id)
                if not self._should_stop():
                    self._save_failure(step)
                if not self._should_stop() and self.failure_reason in {"timeout", "attempts_exhausted", "click_error"}:
                    try:
                        recovered = self._recover(step)
                    except Exception:
                        self.failure_reason = "error"
                        self.logger.exception("Recovery failed: %s", step.id)
                        return False
                    if recovered is not None:
                        index = recovered
                        self._recovery_entry = True
                        continue
                return False
            self.logger.info("Step completed: %s", step.id)
            if self._resume_index is not None:
                self._recovery_entry = self._resume_index > index + 1
                index = self._resume_index
            else:
                self._recovery_entry = False
                index += 1
        return True

    def _run_step(self, step: ScenarioStep) -> bool:
        if step.type == "wait":
            return self._sleep_with_stop(step.timeout_seconds)
        if step.next_step is not None:
            return self._run_confirmed_step(step)

        detector: TemplateDetector | None = None
        if step.type in {"match_and_click", "wait_for_image"}:
            assert step.image is not None
            detector = TemplateDetector(
                step.image,
                step.threshold if step.threshold is not None else self.config.threshold,
                self.config.template_scale_min,
                self.config.template_scale_max,
                self.config.template_scale_step,
            )

        deadline = time.monotonic() + step.timeout_seconds
        confirmation = StateConfirmation(self.scenario.stable_frames)
        while time.monotonic() < deadline and not self._should_stop():
            if step.type != "wait_for_image" and self.max_clicks is not None and self.clicks_done >= self.max_clicks:
                self.failure_reason = "budget"
                self.logger.warning("Step %s rejected: max clicks reached", step.id)
                return False
            if step.type != "wait_for_image" and self.clicks_done:
                remaining = self.config.min_click_interval_seconds - (time.monotonic() - self.last_click_at)
                if remaining > 0:
                    if not self._sleep_with_stop(min(remaining, max(0, deadline - time.monotonic()))):
                        return False
                    continue
            try:
                frame = self.source.grab()
                self.last_frame = frame
            except Exception as exc:
                confirmation.reset()
                self.logger.warning("Step %s capture failed: %s", step.id, exc)
                self._sleep_with_stop(self.config.scan_interval_seconds)
                continue

            if step.type == "click_point":
                assert step.x is not None and step.y is not None
                point_box = frame.to_screen_region(Region(step.x, step.y, 1, 1))
                return self._perform_click_if_allowed(step, frame, point_box.left, point_box.top)

            assert detector is not None
            match = detector.find_best(frame.image)
            stable = confirmation.update([step.id] if match is not None else [])
            if match is None:
                self._sleep_with_stop(self.config.scan_interval_seconds)
                continue
            if not stable:
                self._sleep_with_stop(self.config.scan_interval_seconds)
                continue
            if self._should_stop():
                return False
            if step.type == "wait_for_image":
                if not self._phase_allowed(step):
                    return False
                self.logger.info("Step image detected: id=%s score=%.4f", step.id, match.score)
                return self._sleep_with_stop(step.wait_after_seconds)
            box = frame.to_screen_region(match.box)
            point = self.clicker.pick_point_inside(box, random.Random())
            self.logger.info(
                "Step match: id=%s score=%.4f reference_box=(%d,%d,%d,%d) "
                "screen_box=(%d,%d,%d,%d)",
                step.id,
                match.score,
                match.box.left,
                match.box.top,
                match.box.width,
                match.box.height,
                box.left,
                box.top,
                box.width,
                box.height,
            )
            return self._perform_click_if_allowed(step, frame, point[0], point[1])
        self.failure_reason = "timeout"
        if detector is not None:
            self.logger.error("Step %s match timeout: best_score=%.4f threshold=%.4f location=%s scale=%.3f",
                              step.id, detector.last_score, detector.threshold,
                              detector.last_location, detector.last_scale)
        return False

    def _detector(self, step: ScenarioStep) -> TemplateDetector:
        if step.id not in self._detectors:
            assert step.image is not None
            self._detectors[step.id] = TemplateDetector(
                step.image, step.threshold if step.threshold is not None else self.config.threshold,
                self.config.template_scale_min, self.config.template_scale_max, self.config.template_scale_step,
            )
        return self._detectors[step.id]

    def _run_confirmed_step(self, step: ScenarioStep) -> bool:
        target = next(item for item in self.scenario.steps if item.id == step.next_step)
        detector = self._detector(step)
        candidate_ids = {target.id, *step.recover_to}
        # Observe guarded cycle boundaries even when they are not an allowed transition.
        candidates = [item for item in self.scenario.steps
                      if item.id in candidate_ids or (item.requires_action and item.image != step.image)]
        confirmation = StateConfirmation(self.scenario.stable_frames)
        absent_frames = 0
        deadline = time.monotonic() + step.timeout_seconds
        attempts = 0
        limit = min(step.max_attempts, 2) if self._recovery_entry else step.max_attempts
        departed = False
        response_deadline = 0.0
        click_error = False
        best_score = 0.0
        while time.monotonic() < deadline and not self._should_stop():
            try:
                frame = self.source.grab()
                self.last_frame = frame
            except Exception as exc:
                confirmation.reset()
                absent_frames = 0
                self.logger.warning("Step %s capture failed: %s", step.id, exc)
                self._sleep_with_stop(self.config.scan_interval_seconds)
                continue
            current_match = detector.find_best(frame.image)
            visible = [item for item in candidates if self._detector(item).find_best(frame.image) is not None]
            labels = ([step.id] if current_match is not None else []) + [item.id for item in visible]
            stable = confirmation.update(labels)
            best_score = max(best_score, detector.last_score)
            if self._should_stop():
                return False
            absent_frames = absent_frames + 1 if attempts and current_match is None else 0
            if attempts and absent_frames >= self.scenario.stable_frames:
                if not departed:
                    self.logger.info("Step %s button stably absent; waiting without further clicks", step.id)
                departed = True
            if not stable:
                # A transient miss or overlap pauses actions without committing a transition.
                self._sleep_with_stop(self.config.scan_interval_seconds)
                continue
            if len(labels) > 1:
                self.failure_reason = "ambiguous"
                self.logger.error("Step %s ambiguous stable states: %s", step.id, labels)
                return False
            if visible:
                observed = visible[0]
                if not self._phase_allowed(observed):
                    return False
                if observed.id not in candidate_ids:
                    self.failure_reason = "phase"
                    self.logger.error("Unexpected cycle boundary during %s: %s", step.id, observed.id)
                    return False
                self.logger.info("Stable transition confirmed: %s -> %s frames=%d actions=%s",
                                 step.id, observed.id, self.scenario.stable_frames, sorted(self._cycle_actions))
                self._resume_index = self.scenario.steps.index(observed)
                self.failure_reason = ""
                return True
            now = time.monotonic()
            if current_match is not None and not departed and now >= response_deadline:
                if attempts >= limit:
                    self.failure_reason = "attempts_exhausted"
                    self.logger.error("Step %s exhausted %d click attempts", step.id, limit)
                    return False
                if self.max_clicks is not None and self.clicks_done >= self.max_clicks:
                    self.failure_reason = "budget"
                    return False
                if self.clicks_done and now - self.last_click_at < self.config.min_click_interval_seconds:
                    self._sleep_with_stop(self.config.scan_interval_seconds)
                    continue
                point = self.clicker.pick_point_inside(frame.to_screen_region(current_match.box), random.Random())
                self.logger.info("Step click attempt %d/%d: %s score=%.4f", attempts + 1, limit, step.id, current_match.score)
                success = self._perform_click_if_allowed(step, frame, *point, wait_after=False)
                if not success and self.failure_reason != "click_error":
                    return False
                if self._should_stop():
                    return False
                click_error = not success
                attempts += 1
                confirmation.reset()
                absent_frames = 0
                # A possibly delivered click always gets observation time before any retry.
                response_deadline = time.monotonic() + max(step.response_timeout_seconds, step.wait_after_seconds)
                deadline = time.monotonic() + max(target.timeout_seconds, step.response_timeout_seconds)
            self._sleep_with_stop(self.config.scan_interval_seconds)
        self.failure_reason = "click_error" if click_error else "timeout"
        self.logger.error("Step %s transition timeout: target=%s attempts=%d best_score=%.4f threshold=%.4f",
                          step.id, target.id, attempts, best_score, detector.threshold)
        return False

    def _phase_allowed(self, step: ScenarioStep) -> bool:
        if step.requires_action and (step.requires_action not in self._cycle_actions or self.config.dry_run):
            self.failure_reason = "phase"
            self.logger.error("Cycle boundary rejected: state=%s requires_action=%s cycle_actions=%s dry_run=%s",
                              step.id, step.requires_action, sorted(self._cycle_actions), self.config.dry_run)
            return False
        return True

    def _recover(self, step: ScenarioStep) -> int | None:
        if not step.recover_to or not self.scenario.recovery_scans:
            return None
        candidates = [item for item in self.scenario.steps
                      if item.id in step.recover_to or (item.requires_action and item.image != step.image)]
        for scan in range(1, self.scenario.recovery_scans + 1):
            if self._should_stop():
                return None
            self.logger.info("Recovery scan %d/%d: step=%s candidates=%s", scan,
                             self.scenario.recovery_scans, step.id, step.recover_to)
            confirmation = StateConfirmation(self.scenario.stable_frames)
            for observation in range(self.scenario.stable_frames):
                if self._should_stop():
                    return None
                try:
                    frame = self.source.grab()
                    self.last_frame = frame
                except Exception as exc:
                    confirmation.reset()
                    self.logger.warning("Recovery capture failed: %s", exc)
                else:
                    visible = [item for item in candidates if self._detector(item).find_best(frame.image) is not None]
                    current_visible = step.image is not None and self._detector(step).find_best(frame.image) is not None
                    stable = confirmation.update(([step.id] if current_visible else []) + [item.id for item in visible])
                    if self._should_stop():
                        return None
                    if stable and (len(visible) > 1 or (visible and current_visible)):
                        self.failure_reason = "ambiguous"
                        self.logger.error("Recovery ambiguous: %s", [item.id for item in visible])
                        return None
                    if stable and len(visible) == 1:
                        target = visible[0]
                        if not self._phase_allowed(target):
                            return None
                        if target.id not in step.recover_to:
                            self.failure_reason = "phase"
                            self.logger.error("Unexpected cycle boundary during recovery: %s", target.id)
                            return None
                        self.logger.warning("Recovery resumes at %s after %s; action attempts capped at 2", target.id, step.id)
                        return self.scenario.steps.index(target)
                if observation + 1 < self.scenario.stable_frames:
                    if not self._sleep_with_stop(self.config.scan_interval_seconds):
                        return None
            if scan < self.scenario.recovery_scans:
                if not self._sleep_with_stop(self.scenario.recovery_interval_seconds):
                    return None
        return None

    def _save_failure(self, step: ScenarioStep) -> None:
        self.logger.error("Failure diagnostic: step=%s reason=%s cycles=%d clicks=%d",
                          step.id, self.failure_reason or "unknown", self.cycles_done, self.clicks_done)
        try:
            frame = self.source.grab()
            self.last_frame = frame
            source = "fresh"
        except Exception:
            frame = self.last_frame
            source = "last_capture"
        if frame is None:
            self.logger.warning("Failure screenshot unavailable: no captured frame")
            return
        try:
            directory = self.config.log_file.parent / "failures"
            directory.mkdir(parents=True, exist_ok=True)
            safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", step.id)[:60]
            path = directory / f"failure_{datetime.now():%Y%m%d_%H%M%S_%f}_{safe_id}.png"
            if not cv2.imwrite(str(path), frame.image):
                raise OSError("image encoder returned false")
            for old in sorted(directory.glob("failure_*.png"), key=lambda item: item.stat().st_mtime_ns)[:-20]:
                old.unlink()
            self.logger.error("Failure screenshot: %s source=%s frame_origin=(%d,%d) scale=(%.4f,%.4f)",
                              path, source, frame.left, frame.top, frame.scale_x, frame.scale_y)
        except Exception as exc:
            self.logger.warning("Could not save failure screenshot: %s", exc)

    def _perform_click_if_allowed(self, step: ScenarioStep, frame: Frame, x: int, y: int, *, wait_after: bool = True) -> bool:
        if self._should_stop():
            return False
        frame_region = frame.to_screen_region(
            Region(0, 0, frame.image.shape[1], frame.image.shape[0])
        )
        if not frame_region.contains_point(x, y):
            self.failure_reason = "bounds"
            self.logger.warning("Step %s rejected outside captured client area: x=%d y=%d", step.id, x, y)
            return False
        allowed_region = self._allowed_screen_region(frame)
        if not allowed_region.contains_point(x, y):
            self.failure_reason = "bounds"
            self.logger.warning(
                "Step %s click rejected outside allowed region: x=%d y=%d "
                "allowed=(%d,%d,%d,%d)",
                step.id,
                x,
                y,
                allowed_region.left,
                allowed_region.top,
                allowed_region.width,
                allowed_region.height,
            )
            return False
        if self.max_clicks is not None and self.clicks_done >= self.max_clicks:
            self.failure_reason = "budget"
            self.logger.warning("Step %s click rejected: max clicks reached", step.id)
            return False
        return self._perform_click(step, x, y, wait_after=wait_after)

    def _perform_click(self, step: ScenarioStep, x: int, y: int, *, wait_after: bool = True) -> bool:
        self._attempt_clicked = True
        self._cycle_actions.add(step.id)
        self.clicks_done += 1
        self.last_click_at = time.monotonic()
        if self.config.dry_run:
            self.logger.info("Dry run: would click step=%s x=%d y=%d", step.id, x, y)
        else:
            try:
                self.clicker.click(x, y)
            except Exception as exc:
                from pyautogui import FailSafeException

                self.failure_reason = "failsafe" if isinstance(exc, FailSafeException) else "click_error"
                self.logger.warning("Step %s click failed: %s", step.id, exc)
                return False
        self.last_click_at = time.monotonic()
        return self._sleep_with_stop(step.wait_after_seconds if wait_after else 0)

    def _allowed_screen_region(self, frame: Frame) -> Region:
        if self.config.capture_mode == "window":
            return frame.to_screen_region(self.config.allowed_region)
        return self.config.allowed_region

    def _sleep_with_stop(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._should_stop():
                return False
            time.sleep(max(0, min(0.05, deadline - time.monotonic())))
        return not self._should_stop()

    def _should_stop(self) -> bool:
        return bool(getattr(self.stop_controller, "should_stop", False))
