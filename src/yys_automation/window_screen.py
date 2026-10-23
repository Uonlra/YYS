from __future__ import annotations

import cv2
import time

from src.yys_automation.config import WindowConfig
from src.yys_automation.screen import Frame
from src.yys_automation.window import WindowLocator
from src.yys_automation.window_capture import WindowCaptureError, capture_client


class WindowScreenCapture:
    """Capture a visible target window and normalize it to a reference size."""

    def __init__(self, config: WindowConfig, recovery_attempts: int = 3, recovery_interval_seconds: float = 0.5) -> None:
        self.config = config
        self.locator = WindowLocator()
        self.recovery_attempts = recovery_attempts
        self.recovery_interval_seconds = recovery_interval_seconds

    def grab(self) -> Frame:
        last_error: Exception | None = None
        window = None
        for attempt in range(1, self.recovery_attempts + 1):
            try:
                window = self.locator.find_first(
                    self.config.title_contains,
                    handle=self.config.handle,
                    process_id=self.config.process_id,
                )
                if window is None:
                    raise WindowCaptureError(f"Window not found: {self.config.title_contains}")
                image, _method = capture_client(window)
                break
            except Exception as exc:
                last_error = exc
                if attempt < self.recovery_attempts:
                    time.sleep(self.recovery_interval_seconds)
        else:
            raise WindowCaptureError(
                f"Window capture failed after {self.recovery_attempts} attempts: {last_error}"
            ) from last_error

        assert window is not None
        actual_height, actual_width = image.shape[:2]
        normalized = cv2.resize(
            image,
            (self.config.reference_width, self.config.reference_height),
            interpolation=cv2.INTER_AREA,
        )
        return Frame(
            image=normalized,
            left=window.client_left,
            top=window.client_top,
            scale_x=actual_width / self.config.reference_width,
            scale_y=actual_height / self.config.reference_height,
        )
