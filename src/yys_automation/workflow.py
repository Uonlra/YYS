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

    def run(self) -> bool:
        for attempt in range(1, self.scenario.max_retries + 1):
            self.logger.info(
                "Scenario attempt %d/%d: %s",
                attempt,
                self.scenario.max_retries,
                self.scenario.name,
            )
            if self._run_once():
                self.logger.info("Scenario completed: %s", self.scenario.name)
                return True
            if self._should_stop():
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
        if step.type == "match_and_click":
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
            try:
                frame = self.source.grab()
            except Exception as exc:
                self.logger.warning("Step %s capture failed: %s", step.id, exc)
                self._sleep_with_stop(self.config.scan_interval_seconds)
                continue

            if step.type == "click_point":
                assert step.x is not None and step.y is not None
                point_box = frame.to_screen_region(Region(step.x, step.y, 1, 1))
                return self._perform_click(step, point_box.left, point_box.top)

            assert detector is not None
            match = detector.find_best(frame.image)
            if match is None:
                self._sleep_with_stop(self.config.scan_interval_seconds)
                continue
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
            return self._perform_click(step, point[0], point[1])
        return False

    def _perform_click(self, step: ScenarioStep, x: int, y: int) -> bool:
        if self.config.dry_run:
            self.logger.info("Dry run: would click step=%s x=%d y=%d", step.id, x, y)
        else:
            try:
                self.clicker.click(x, y)
            except Exception as exc:
                self.logger.warning("Step %s click failed: %s", step.id, exc)
                return False
        return self._sleep_with_stop(step.wait_after_seconds)

    def _sleep_with_stop(self, seconds: float) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            if self._should_stop():
                return False
            time.sleep(min(0.05, deadline - time.monotonic()))
        return True

    def _should_stop(self) -> bool:
        return bool(getattr(self.stop_controller, "should_stop", False))
