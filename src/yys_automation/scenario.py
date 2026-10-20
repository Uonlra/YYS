from __future__ import annotations

from dataclasses import dataclass
import math
from pathlib import Path
from typing import Any, Literal

import yaml

from src.yys_automation.config import AppConfig


STEP_TYPES = {"match_and_click", "wait_for_image", "click_point", "wait"}


@dataclass(frozen=True)
class ScenarioStep:
    id: str
    type: str
    image: Path | None
    threshold: float | None
    timeout_seconds: float
    x: int | None
    y: int | None
    wait_after_seconds: float
    max_attempts: int = 1
    next_step: str | None = None
    response_timeout_seconds: float = 3.0
    recover_to: tuple[str, ...] = ()
    requires_action: str | None = None


@dataclass(frozen=True)
class Scenario:
    name: str
    max_retries: int
    retry_after_clicks: bool
    steps: tuple[ScenarioStep, ...]
    repeat_count: int | None = 1
    max_cycles: int = 800
    max_clicks: int | Literal["auto"] | None = None
    recovery_scans: int = 0
    recovery_interval_seconds: float = 1.0
    stable_frames: int = 1

    @property
    def cycle_limit(self) -> int:
        return self.repeat_count if self.repeat_count is not None else self.max_cycles

    @property
    def clicks_per_cycle(self) -> int:
        return sum(step.type in {"match_and_click", "click_point"} for step in self.steps)

    @property
    def click_attempts_per_cycle(self) -> int:
        return sum(step.max_attempts for step in self.steps if step.type in {"match_and_click", "click_point"})

    def click_budget(self, config: AppConfig) -> tuple[int | None, str]:
        if self.max_clicks == "auto":
            return self.click_attempts_per_cycle * self.cycle_limit, "scenario.auto"
        if self.max_clicks is not None:
            return self.max_clicks, "scenario.max_clicks"
        return config.max_clicks, "config.max_clicks"


def load_scenario(path: Path) -> Scenario:
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}
    if not isinstance(raw, dict):
        raise ValueError("scenario root must be a mapping")

    name = str(raw.get("name", path.stem))
    max_retries = _integer(raw.get("max_retries", 3), "max_retries")
    if max_retries < 1:
        raise ValueError("scenario max_retries must be >= 1")
    retry_after_clicks = raw.get("retry_after_clicks", False)
    if not isinstance(retry_after_clicks, bool):
        raise ValueError("scenario retry_after_clicks must be a boolean")
    max_cycles = _integer(raw.get("max_cycles", 800), "max_cycles")
    if max_cycles < 1:
        raise ValueError("scenario max_cycles must be >= 1")
    repeat_value = raw.get("repeat_count", 1)
    repeat_count = None if repeat_value is None else _integer(repeat_value, "repeat_count")
    if repeat_count is not None and not 1 <= repeat_count <= max_cycles:
        raise ValueError("scenario repeat_count must be null or between 1 and max_cycles")
    recovery_scans = _integer(raw.get("recovery_scans", 0), "recovery_scans")
    if not 0 <= recovery_scans <= 2:
        raise ValueError("recovery_scans must be between 0 and 2")
    recovery_interval = _finite_float(raw.get("recovery_interval_seconds", 1), "recovery_interval_seconds")
    if recovery_interval <= 0:
        raise ValueError("recovery_interval_seconds must be positive")
    stable_frames = _integer(raw.get("stable_frames", 1), "stable_frames")
    if not 1 <= stable_frames <= 10:
        raise ValueError("stable_frames must be between 1 and 10")
    max_clicks = None
    if "max_clicks" in raw:
        value = raw["max_clicks"]
        if value == "auto":
            max_clicks = "auto"
        elif type(value) is int and value >= 0:
            max_clicks = value
        else:
            raise ValueError("scenario max_clicks must be auto or a non-negative integer; omit to use config default")

    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("scenario steps must be a non-empty list")

    steps: list[ScenarioStep] = []
    step_ids: set[str] = set()
    for index, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"scenario step {index} must be a mapping")
        step_id = str(item.get("id", f"step_{index}"))
        if not step_id.strip():
            raise ValueError(f"scenario step {index}: id must not be empty")
        if step_id in step_ids:
            raise ValueError(f"scenario step {index}: duplicate id {step_id!r}")
        step_ids.add(step_id)
        step_type = str(item.get("type", ""))
        if step_type not in STEP_TYPES:
            raise ValueError(f"step {step_id}: unsupported type {step_type!r}")

        image: Path | None = None
        if item.get("image") is not None:
            image = _resolve_path(path.parent, str(item["image"]))
        if step_type in {"match_and_click", "wait_for_image"} and image is None:
            raise ValueError(f"step {step_id}: image is required")

        x = _integer(item["x"], f"step {step_id} x") if item.get("x") is not None else None
        y = _integer(item["y"], f"step {step_id} y") if item.get("y") is not None else None
        if step_type == "click_point" and (x is None or y is None):
            raise ValueError(f"step {step_id}: x and y are required")

        timeout = _finite_float(item.get("timeout_seconds", 30.0), f"step {step_id} timeout_seconds")
        wait_after = _finite_float(item.get("wait_after_seconds", 0.5), f"step {step_id} wait_after_seconds")
        threshold = (
            _finite_float(item["threshold"], f"step {step_id} threshold")
            if item.get("threshold") is not None
            else None
        )
        if timeout <= 0 or wait_after < 0:
            raise ValueError(f"step {step_id}: invalid timeout or wait_after_seconds")
        if threshold is not None and not 0.0 < threshold <= 1.0:
            raise ValueError(f"step {step_id}: threshold must be between 0 and 1")
        max_attempts = _integer(item.get("max_attempts", 1), f"step {step_id} max_attempts")
        next_step = item.get("next_step")
        response_timeout = _finite_float(item.get("response_timeout_seconds", 3), "response_timeout_seconds")
        recover_to = item.get("recover_to", [])
        requires_action = item.get("requires_action")
        if requires_action is not None and (not isinstance(requires_action, str) or not requires_action):
            raise ValueError(f"step {step_id}: requires_action must be a non-empty step id")
        if requires_action is not None and step_type != "wait_for_image":
            raise ValueError(f"step {step_id}: requires_action is only supported on wait_for_image")
        if not 1 <= max_attempts <= 3:
            raise ValueError(f"step {step_id}: max_attempts must be between 1 and 3")
        if next_step is not None and (not isinstance(next_step, str) or not next_step):
            raise ValueError(f"step {step_id}: next_step must be a non-empty step id")
        if response_timeout <= 0:
            raise ValueError(f"step {step_id}: response_timeout_seconds must be positive")
        if not isinstance(recover_to, list) or any(not isinstance(value, str) for value in recover_to):
            raise ValueError(f"step {step_id}: recover_to must be a list of step ids")
        if max_attempts > 1 and (step_type != "match_and_click" or next_step is None):
            raise ValueError(f"step {step_id}: retries require match_and_click with next_step")
        if next_step is not None and step_type != "match_and_click":
            raise ValueError(f"step {step_id}: next_step requires match_and_click")

        steps.append(
            ScenarioStep(
                id=step_id,
                type=step_type,
                image=image,
                threshold=threshold,
                timeout_seconds=timeout,
                x=x,
                y=y,
                wait_after_seconds=wait_after,
                max_attempts=max_attempts,
                next_step=next_step,
                response_timeout_seconds=response_timeout,
                recover_to=tuple(recover_to),
                requires_action=requires_action,
            )
        )

    indices = {step.id: index for index, step in enumerate(steps)}
    for index, step in enumerate(steps):
        if step.requires_action is not None:
            action_index = indices.get(step.requires_action)
            if action_index is None or action_index >= index or steps[action_index].type not in {"match_and_click", "click_point"}:
                raise ValueError(f"step {step.id}: requires_action must reference an earlier click step")
        if step.next_step is not None and indices.get(step.next_step) != index + 1:
            raise ValueError(f"step {step.id}: next_step must reference the immediately following step")
        for target_id in (*step.recover_to, *((step.next_step,) if step.next_step else ())):
            target_index = indices.get(target_id)
            if target_index is None or target_index <= index:
                raise ValueError(f"step {step.id}: target {target_id!r} must reference a later step")
            if steps[target_index].image is None:
                raise ValueError(f"step {step.id}: target {target_id!r} must have an image")
            if steps[target_index].type not in {"match_and_click", "wait_for_image"}:
                raise ValueError(f"step {step.id}: target {target_id!r} must revalidate its image")

    return Scenario(
        name=name,
        max_retries=max_retries,
        retry_after_clicks=retry_after_clicks,
        steps=tuple(steps),
        repeat_count=repeat_count,
        max_cycles=max_cycles,
        max_clicks=max_clicks,
        recovery_scans=recovery_scans,
        recovery_interval_seconds=recovery_interval,
        stable_frames=stable_frames,
    )


def validate_scenario(path: Path, config: AppConfig | None = None) -> list[str]:
    """Return human-readable validation errors without starting the task."""
    errors: list[str] = []
    try:
        scenario = load_scenario(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [str(exc)]
    if config is not None and config.capture_mode != "window":
        errors.append("scenario mode requires capture_mode: window")
    for step in scenario.steps:
        if step.type == "click_point" and config is not None:
            assert step.x is not None and step.y is not None
            if not (0 <= step.x < config.window.reference_width and 0 <= step.y < config.window.reference_height):
                errors.append(
                    f"step {step.id}: click point ({step.x},{step.y}) is outside reference window "
                    f"{config.window.reference_width}x{config.window.reference_height}"
                )
            elif not config.allowed_region.contains_point(step.x, step.y):
                errors.append(f"step {step.id}: click point ({step.x},{step.y}) is outside allowed_region")
        if step.image is not None:
            if not step.image.exists():
                errors.append(f"step {step.id}: image not found: {step.image}")
            else:
                import cv2

                if cv2.imread(str(step.image), cv2.IMREAD_COLOR) is None:
                    errors.append(f"step {step.id}: image cannot be decoded: {step.image}")
    return errors


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{name} must be a finite number")
    return number


def _integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be an integer")
    return number
