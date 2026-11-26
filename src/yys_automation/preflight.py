"""Read-only recognition preview using the same capture and detector as a run."""
from __future__ import annotations

from dataclasses import dataclass, replace
import time

import cv2
import numpy as np

from src.yys_automation.config import AppConfig, Region
from src.yys_automation.detector import TemplateDetector
from src.yys_automation.scenario import Scenario
from src.yys_automation.screen import Frame
from src.yys_automation.window import WindowInfo, WindowLocator
from src.yys_automation.window_screen import WindowScreenCapture


def with_window_identity(config: AppConfig, identity: tuple[int, int] | None) -> AppConfig:
    if identity is None:
        return config
    handle, process_id = identity
    if any(isinstance(value, bool) or not isinstance(value, int) or value <= 0 for value in identity):
        raise ValueError("Window handle and process ID must be positive integers")
    return replace(config, window=replace(config.window, title_contains="", handle=handle, process_id=process_id))


@dataclass(frozen=True)
class TargetPreview:
    id: str
    kind: str
    score: float | None
    threshold: float | None
    box: Region | None
    point: tuple[int, int] | None
    screen_point: tuple[int, int] | None
    in_bounds: bool
    matched: bool


@dataclass(frozen=True)
class PreviewResult:
    window: WindowInfo
    frame: Frame
    annotated: np.ndarray
    targets: tuple[TargetPreview, ...]
    preferred_id: str | None
    duration_seconds: float


def inspect_frame(config: AppConfig, scenario: Scenario, frame: Frame,
                  window: WindowInfo, selected_step_id: str | None = None, *,
                  only_selected: bool = False) -> PreviewResult:
    """Recognize one immutable frame. No input backend or hotkey listener is used."""
    started = time.perf_counter()
    image = frame.image.copy()
    roi = config.allowed_region
    cv2.rectangle(image, (roi.left, roi.top), (roi.right - 1, roi.bottom - 1), (220, 140, 40), 2)
    targets = []
    for step in scenario.steps:
        if (only_selected or scenario.execution_mode != "match_any") and step.id != selected_step_id:
            continue
        match = None
        score = None
        box = None
        point = None
        threshold = None
        if step.image is not None:
            threshold = step.threshold if step.threshold is not None else config.threshold
            detector = TemplateDetector(
                step.image, threshold,
                config.template_scale_min, config.template_scale_max, config.template_scale_step,
                search_region=config.allowed_region,
                coarse_to_fine=scenario.execution_mode == "match_any" and scenario.match_any_detection_mode == "coarse_to_fine",
            )
            match = detector.find_best(frame.image)
            box = detector.last_box
            score = detector.last_score if box is not None else None
            if match is not None:
                if step.type == "match_and_click":
                    point = (box.left + box.width // 2, box.top + box.height // 2)
        elif step.type == "click_point":
            point = (step.x, step.y)
        screen_point = None
        in_bounds = False
        if point is not None:
            x, y = point
            screen_point = (frame.left + round(x * frame.scale_x), frame.top + round(y * frame.scale_y))
            if box is not None:
                screen_box = frame.to_screen_region(box)
                screen_point = (screen_box.left + screen_box.width // 2, screen_box.top + screen_box.height // 2)
            in_bounds = (roi.contains_point(x, y) and 0 <= x < frame.image.shape[1] and 0 <= y < frame.image.shape[0]
                         and frame.to_screen_region(roi).contains_point(*screen_point)
                         and frame.to_screen_region(Region(0, 0, frame.image.shape[1], frame.image.shape[0])).contains_point(*screen_point))
        targets.append(TargetPreview(step.id, step.type, score, threshold, box, point, screen_point,
                                     in_bounds, match is not None))
    # Match-any picks by score first and config order breaks ties, as in WorkflowRunner.
    matches = [item for item in targets if item.matched and item.kind == "match_and_click"]
    preferred = max(matches, key=lambda item: item.score).id if matches and scenario.execution_mode == "match_any" and not only_selected else None
    for item in targets:
        color = (80, 170, 60) if item.matched else (20, 170, 240)
        if item.box is not None:
            box = item.box
            cv2.rectangle(image, (box.left, box.top), (box.right - 1, box.bottom - 1), color, 3 if item.id == preferred else 1)
            cv2.putText(image, f"{item.id}: {item.score:.3f}", (box.left, max(16, box.top - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
        if item.point is not None:
            cv2.drawMarker(image, item.point, (70, 70, 230), cv2.MARKER_CROSS, 18, 2)
    return PreviewResult(window, frame, image, tuple(targets), preferred, time.perf_counter() - started)


def capture_frame(config: AppConfig) -> tuple[Frame, WindowInfo]:
    if config.capture_mode != "window":
        raise ValueError("运行前预览需要 capture_mode: window")
    window = WindowLocator().find_first(config.window.title_contains, handle=config.window.handle,
                                        process_id=config.window.process_id)
    if window is None:
        raise ValueError("未找到目标窗口。请刷新列表重新选择，或检查全局窗口配置。")
    # Bind this capture to the resolved identity rather than resolving an ambiguous title again.
    pinned = with_window_identity(config, (window.handle, window.process_id))
    frame = WindowScreenCapture(pinned.window, recovery_attempts=1).grab()
    window = replace(window, client_left=frame.left, client_top=frame.top,
                     client_width=round(frame.image.shape[1] * frame.scale_x),
                     client_height=round(frame.image.shape[0] * frame.scale_y))
    return frame, window


def capture_preview(config: AppConfig, scenario: Scenario, selected_step_id: str | None = None) -> PreviewResult:
    frame, window = capture_frame(config)
    return inspect_frame(config, scenario, frame, window, selected_step_id)
