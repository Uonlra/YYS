from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class Region:
    left: int
    top: int
    width: int
    height: int

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    def contains_point(self, x: int, y: int) -> bool:
        return self.left <= x < self.right and self.top <= y < self.bottom


@dataclass(frozen=True)
class DurationRange:
    min: float
    max: float


@dataclass(frozen=True)
class Jitter:
    x: int
    y: int


@dataclass(frozen=True)
class WindowConfig:
    title_contains: str
    reference_width: int
    reference_height: int


@dataclass(frozen=True)
class AppConfig:
    target_image: Path
    threshold: float
    allowed_region: Region
    scan_interval_seconds: float
    min_click_interval_seconds: float
    max_clicks: int | None
    move_duration_seconds: DurationRange
    click_jitter_pixels: Jitter
    startup_delay_seconds: float
    dry_run: bool
    log_file: Path
    window: WindowConfig
    capture_mode: str
    template_scale_min: float
    template_scale_max: float
    template_scale_step: float


def load_config(path: Path) -> AppConfig:
    with path.open("r", encoding="utf-8") as file:
        raw = yaml.safe_load(file) or {}

    base_dir = path.parent
    target_image = _resolve_path(base_dir, raw["target_image"])
    log_file = _resolve_path(base_dir, raw.get("log_file", "logs/automation.log"))
    region = raw["allowed_region"]
    duration = raw.get("move_duration_seconds", {})
    jitter = raw.get("click_jitter_pixels", {})

    config = AppConfig(
        target_image=target_image,
        threshold=float(raw.get("threshold", 0.86)),
        allowed_region=Region(
            left=int(region["left"]),
            top=int(region["top"]),
            width=int(region["width"]),
            height=int(region["height"]),
        ),
        scan_interval_seconds=float(raw.get("scan_interval_seconds", 0.25)),
        min_click_interval_seconds=float(raw.get("min_click_interval_seconds", 2.0)),
        max_clicks=_optional_int(raw.get("max_clicks", 10)),
        move_duration_seconds=DurationRange(
            min=float(duration.get("min", 0.2)),
            max=float(duration.get("max", 0.8)),
        ),
        click_jitter_pixels=Jitter(
            x=int(jitter.get("x", 6)),
            y=int(jitter.get("y", 4)),
        ),
        startup_delay_seconds=float(raw.get("startup_delay_seconds", 3.0)),
        dry_run=bool(raw.get("dry_run", False)),
        log_file=log_file,
        window=WindowConfig(
            title_contains=str(raw.get("window", {}).get("title_contains", "阴阳师")),
            reference_width=int(raw.get("window", {}).get("reference_width", 1280)),
            reference_height=int(raw.get("window", {}).get("reference_height", 720)),
        ),
        capture_mode=str(raw.get("capture_mode", "desktop")),
        template_scale_min=float(raw.get("recognition", {}).get("template_scale_min", 0.75)),
        template_scale_max=float(raw.get("recognition", {}).get("template_scale_max", 1.35)),
        template_scale_step=float(raw.get("recognition", {}).get("template_scale_step", 0.05)),
    )
    _validate_config(config)
    return config


def _resolve_path(base_dir: Path, value: str) -> Path:
    path = Path(value)
    if path.is_absolute():
        return path
    return base_dir / path


def _optional_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _validate_config(config: AppConfig) -> None:
    if not config.target_image.exists():
        raise FileNotFoundError(f"Target image not found: {config.target_image}")
    if not 0.0 < config.threshold <= 1.0:
        raise ValueError("threshold must be between 0 and 1")
    if config.allowed_region.width <= 0 or config.allowed_region.height <= 0:
        raise ValueError("allowed_region width and height must be positive")
    if config.scan_interval_seconds <= 0:
        raise ValueError("scan_interval_seconds must be positive")
    if config.min_click_interval_seconds <= 0:
        raise ValueError("min_click_interval_seconds must be positive")
    if config.max_clicks is not None and config.max_clicks < 0:
        raise ValueError("max_clicks must be null or >= 0")
    if config.move_duration_seconds.min < 0:
        raise ValueError("move_duration_seconds.min must be >= 0")
    if config.move_duration_seconds.max < config.move_duration_seconds.min:
        raise ValueError("move_duration_seconds.max must be >= min")
    if config.window.reference_width <= 0 or config.window.reference_height <= 0:
        raise ValueError("window reference dimensions must be positive")
    if config.capture_mode not in {"desktop", "window"}:
        raise ValueError("capture_mode must be 'desktop' or 'window'")
    if config.template_scale_min <= 0:
        raise ValueError("recognition.template_scale_min must be positive")
    if config.template_scale_max < config.template_scale_min:
        raise ValueError("recognition.template_scale_max must be >= min")
    if config.template_scale_step <= 0:
        raise ValueError("recognition.template_scale_step must be positive")
