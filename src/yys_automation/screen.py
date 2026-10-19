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
