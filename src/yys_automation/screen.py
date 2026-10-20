from __future__ import annotations

from dataclasses import dataclass

import cv2
import mss
import numpy as np

from src.yys_automation.config import Region


@dataclass(frozen=True)
class Frame:
    image: np.ndarray
    left: int
    top: int
    scale_x: float = 1.0
    scale_y: float = 1.0

    def to_screen_region(self, region: Region) -> Region:
        return Region(
            left=self.left + round(region.left * self.scale_x),
            top=self.top + round(region.top * self.scale_y),
            width=max(1, round(region.width * self.scale_x)),
            height=max(1, round(region.height * self.scale_y)),
        )


class ScreenCapture:
    def __init__(self, region: Region) -> None:
        self.region = region
        self._sct = mss.mss()

    def grab(self) -> Frame:
        monitor = {
            "left": self.region.left,
            "top": self.region.top,
            "width": self.region.width,
            "height": self.region.height,
        }
        raw = np.array(self._sct.grab(monitor))
        image = cv2.cvtColor(raw, cv2.COLOR_BGRA2BGR)
        return Frame(image=image, left=self.region.left, top=self.region.top)

    def close(self) -> None:
        self._sct.close()

    def __enter__(self) -> ScreenCapture:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
