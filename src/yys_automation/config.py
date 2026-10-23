from __future__ import annotations

from dataclasses import dataclass
import math
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
    handle: int | None = None
    process_id: int | None = None


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
    if not isinstance(raw, dict):
        raise ValueError("config root must be a mapping")

    base_dir = path.parent
    target_image = _resolve_path(base_dir, str(_required(raw, "target_image")))
    log_file = _resolve_path(base_dir, str(raw.get("log_file", "logs/automation.log")))
    region = _mapping(raw, "allowed_region", required=True)
    duration = _mapping(raw, "move_duration_seconds")
    jitter = _mapping(raw, "click_jitter_pixels")
    window = _mapping(raw, "window")
    recognition = _mapping(raw, "recognition")

    window_identity_configured = "handle" in window or "process_id" in window
    config = AppConfig(
        target_image=target_image,
        threshold=_finite_float(raw.get("threshold", 0.86), "threshold"),
        allowed_region=Region(
            left=_integer(region, "left"),
            top=_integer(region, "top"),
            width=_integer(region, "width"),
            height=_integer(region, "height"),
        ),
        scan_interval_seconds=_finite_float(raw.get("scan_interval_seconds", 0.25), "scan_interval_seconds"),
        min_click_interval_seconds=_finite_float(
            raw.get("min_click_interval_seconds", 2.0), "min_click_interval_seconds"
        ),
        max_clicks=_optional_int(raw.get("max_clicks", 10)),
        move_duration_seconds=DurationRange(
            min=_finite_float(duration.get("min", 0.2), "move_duration_seconds.min"),
            max=_finite_float(duration.get("max", 0.8), "move_duration_seconds.max"),
        ),
        click_jitter_pixels=Jitter(
            x=_integer(jitter, "x", 6),
            y=_integer(jitter, "y", 4),
        ),
        startup_delay_seconds=_finite_float(raw.get("startup_delay_seconds", 3.0), "startup_delay_seconds"),
        dry_run=_boolean(raw.get("dry_run", False), "dry_run"),
        log_file=log_file,
        window=WindowConfig(
            title_contains=str(window.get("title_contains", "" if window_identity_configured else "阴阳师")),
            reference_width=_integer(window, "reference_width", 1280),
            reference_height=_integer(window, "reference_height", 720),
            handle=_optional_integer(window.get("handle"), "window.handle"),
            process_id=_optional_integer(window.get("process_id"), "window.process_id"),
        ),
        capture_mode=str(raw.get("capture_mode", "desktop")),
        template_scale_min=_finite_float(recognition.get("template_scale_min", 0.75), "recognition.template_scale_min"),
        template_scale_max=_finite_float(recognition.get("template_scale_max", 1.35), "recognition.template_scale_max"),
        template_scale_step=_finite_float(recognition.get("template_scale_step", 0.05), "recognition.template_scale_step"),
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
    return _as_integer(value, "max_clicks")


def _optional_integer(value: Any, name: str) -> int | None:
    if value is None:
        return None
    return _as_integer(value, name)


def _required(mapping: dict[str, Any], key: str) -> Any:
    if key not in mapping:
        raise ValueError(f"missing required config field: {key}")
    return mapping[key]


def _mapping(parent: dict[str, Any], key: str, *, required: bool = False) -> dict[str, Any]:
    if key not in parent and not required:
        return {}
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ValueError(f"config field {key} must be a mapping")
    return value


def _as_integer(value: Any, name: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be an integer")
    try:
        number = int(value)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{name} must be an integer")
    return number


def _integer(mapping: dict[str, Any], key: str, default: int | None = None) -> int:
    value = mapping.get(key, default)
    if value is None:
        raise ValueError(f"missing required config field: {key}")
    return _as_integer(value, key)


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


def _boolean(value: Any, name: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{name} must be a boolean")
    return value


def _validate_config(config: AppConfig) -> None:
    if not config.target_image.exists():
        raise FileNotFoundError(f"Target image not found: {config.target_image}")
    import cv2

    if cv2.imread(str(config.target_image), cv2.IMREAD_COLOR) is None:
        raise ValueError(f"Target image cannot be decoded: {config.target_image}")
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
    if config.startup_delay_seconds < 0:
        raise ValueError("startup_delay_seconds must be >= 0")
    if config.click_jitter_pixels.x < 0 or config.click_jitter_pixels.y < 0:
        raise ValueError("click_jitter_pixels values must be >= 0")
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
    if not config.window.title_contains.strip() and config.window.handle is None and config.window.process_id is None:
        raise ValueError("window.title_contains must not be empty when no window identity is set")
    if config.window.handle is not None and config.window.handle <= 0:
        raise ValueError("window.handle must be a positive integer")
    if config.window.process_id is not None and config.window.process_id <= 0:
        raise ValueError("window.process_id must be a positive integer")
    if config.capture_mode == "window":
        if config.allowed_region.left < 0 or config.allowed_region.top < 0:
            raise ValueError("window allowed_region left and top must be >= 0")
        if config.allowed_region.right > config.window.reference_width:
            raise ValueError("window allowed_region exceeds reference_width")
        if config.allowed_region.bottom > config.window.reference_height:
            raise ValueError("window allowed_region exceeds reference_height")
