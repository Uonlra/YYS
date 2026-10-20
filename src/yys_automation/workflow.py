from __future__ import annotations

import logging
import random
import time
from pathlib import Path
from typing import Protocol

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

    def run(self) -> bool:
        cycle_limit = self.scenario.cycle_limit
        clicks_per_cycle = self.scenario.clicks_per_cycle
        self.logger.info(
            "Scenario budget: clicks_per_cycle=%d cycles=%d max_clicks=%s source=%s dry_run=%s",
            clicks_per_cycle, cycle_limit,
            self.max_clicks if self.max_clicks is not None else "unlimited",
            self.budget_source, self.config.dry_run,
        )
        for cycle in range(1, cycle_limit + 1):
            if self._should_stop():
                return False
            if self.max_clicks is not None and self.clicks_done + clicks_per_cycle > self.max_clicks:
                self.logger.warning(
                    "Scenario stopped before cycle %d: insufficient click budget "
                    "done=%d max=%d required=%d completed_cycles=%d",
                    cycle, self.clicks_done, self.max_clicks, clicks_per_cycle, self.cycles_done,
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
            if self._attempt_clicked and not self.scenario.retry_after_clicks:
                self.logger.error("Scenario retry stopped after a click: %s", self.scenario.name)
                break
            self.logger.warning("Scenario attempt failed: %d/%d", attempt, self.scenario.max_retries)
        self.logger.error("Scenario failed: %s", self.scenario.name)
        return False

    def _run_once(self) -> bool:
        for step in self.scenario.steps:
            if self._should_stop():
                return False
            self.logger.info("Step started: %s type=%s", step.id, step.type)
            if not self._run_step(step):
                self.logger.error("Step failed: %s", step.id)
                return False
            self.logger.info("Step completed: %s", step.id)
        return True

    def _run_step(self, step: ScenarioStep) -> bool:
        if step.type == "wait":
            return self._sleep_with_stop(step.timeout_seconds)

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
        while time.monotonic() < deadline and not self._should_stop():
            if step.type != "wait_for_image" and self.max_clicks is not None and self.clicks_done >= self.max_clicks:
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
            except Exception as exc:
                self.logger.warning("Step %s capture failed: %s", step.id, exc)
                self._sleep_with_stop(self.config.scan_interval_seconds)
                continue

            if step.type == "click_point":
                assert step.x is not None and step.y is not None
                point_box = frame.to_screen_region(Region(step.x, step.y, 1, 1))
                return self._perform_click_if_allowed(step, frame, point_box.left, point_box.top)

            assert detector is not None
            match = detector.find_best(frame.image)
            if match is None:
                self._sleep_with_stop(self.config.scan_interval_seconds)
                continue
            if self._should_stop():
                return False
            if step.type == "wait_for_image":
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
        return False

    def _perform_click_if_allowed(self, step: ScenarioStep, frame: Frame, x: int, y: int) -> bool:
        if self._should_stop():
            return False
        frame_region = frame.to_screen_region(
            Region(0, 0, frame.image.shape[1], frame.image.shape[0])
        )
        if not frame_region.contains_point(x, y):
            self.logger.warning("Step %s rejected outside captured client area: x=%d y=%d", step.id, x, y)
            return False
        allowed_region = self._allowed_screen_region(frame)
        if not allowed_region.contains_point(x, y):
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
            self.logger.warning("Step %s click rejected: max clicks reached", step.id)
            return False
        return self._perform_click(step, x, y)

    def _perform_click(self, step: ScenarioStep, x: int, y: int) -> bool:
        self._attempt_clicked = True
        self.clicks_done += 1
        self.last_click_at = time.monotonic()
        if self.config.dry_run:
            self.logger.info("Dry run: would click step=%s x=%d y=%d", step.id, x, y)
        else:
            try:
                self.clicker.click(x, y)
            except Exception as exc:
                self.logger.warning("Step %s click failed: %s", step.id, exc)
                return False
        self.last_click_at = time.monotonic()
        return self._sleep_with_stop(step.wait_after_seconds)

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
