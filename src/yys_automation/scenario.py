from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


STEP_TYPES = {"match_and_click", "click_point", "wait"}


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


@dataclass(frozen=True)
class Scenario:
    name: str
    max_retries: int
    retry_after_clicks: bool
    steps: tuple[ScenarioStep, ...]


def load_scenario(path: Path) -> Scenario:
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    name = str(raw.get("name", path.stem))
    max_retries = int(raw.get("max_retries", 3))
    if max_retries < 1:
        raise ValueError("scenario max_retries must be >= 1")
    retry_after_clicks = raw.get("retry_after_clicks", False)
    if not isinstance(retry_after_clicks, bool):
        raise ValueError("scenario retry_after_clicks must be a boolean")

    raw_steps = raw.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("scenario steps must be a non-empty list")

    steps: list[ScenarioStep] = []
    for index, item in enumerate(raw_steps, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"scenario step {index} must be a mapping")
        step_id = str(item.get("id", f"step_{index}"))
        step_type = str(item.get("type", ""))
        if step_type not in STEP_TYPES:
            raise ValueError(f"step {step_id}: unsupported type {step_type!r}")

        image: Path | None = None
        if item.get("image") is not None:
            image = _resolve_path(path.parent, str(item["image"]))
        if step_type == "match_and_click" and image is None:
            raise ValueError(f"step {step_id}: image is required")

        x = int(item["x"]) if item.get("x") is not None else None
        y = int(item["y"]) if item.get("y") is not None else None
        if step_type == "click_point" and (x is None or y is None):
            raise ValueError(f"step {step_id}: x and y are required")

        timeout = float(item.get("timeout_seconds", 30.0))
        wait_after = float(item.get("wait_after_seconds", 0.5))
        threshold = float(item["threshold"]) if item.get("threshold") is not None else None
        if timeout <= 0 or wait_after < 0:
            raise ValueError(f"step {step_id}: invalid timeout or wait_after_seconds")
        if threshold is not None and not 0.0 < threshold <= 1.0:
            raise ValueError(f"step {step_id}: threshold must be between 0 and 1")

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
            )
        )

    return Scenario(
        name=name,
        max_retries=max_retries,
        retry_after_clicks=retry_after_clicks,
        steps=tuple(steps),
    )


def validate_scenario(path: Path) -> list[str]:
    """Return human-readable validation errors without starting the task."""
    errors: list[str] = []
    try:
        scenario = load_scenario(path)
    except (OSError, ValueError, yaml.YAMLError) as exc:
        return [str(exc)]
    for step in scenario.steps:
        if step.image is not None and not step.image.exists():
            errors.append(f"step {step.id}: image not found: {step.image}")
    return errors


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else base_dir / path
