from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from src.yys_automation.config import Region


@dataclass(frozen=True)
class Match:
    score: float
    box: Region


class TemplateDetector:
    def __init__(
        self,
        target_image: Path,
        threshold: float,
        scale_min: float = 1.0,
        scale_max: float = 1.0,
        scale_step: float = 0.05,
    ) -> None:
        template = cv2.imread(str(target_image), cv2.IMREAD_COLOR)
        if template is None:
            raise ValueError(f"Could not read target image: {target_image}")

        self.template = template
        self.threshold = threshold
        self.scale_min = scale_min
        self.scale_max = scale_max
        self.scale_step = scale_step
        self.template_height, self.template_width = template.shape[:2]
        self.last_score = 0.0
        self.last_location = (0, 0)
        self.last_scale = 1.0

    def find_best(self, image: np.ndarray) -> Match | None:
        best: tuple[float, tuple[int, int], float, int, int] | None = None
        scale = self.scale_min
        while scale <= self.scale_max + self.scale_step / 10:
            width = max(1, round(self.template_width * scale))
            height = max(1, round(self.template_height * scale))
            if width <= image.shape[1] and height <= image.shape[0]:
                if width == self.template_width and height == self.template_height:
                    template = self.template
                else:
                    template = cv2.resize(
                        self.template,
                        (width, height),
                        interpolation=cv2.INTER_AREA,
                    )
                result = cv2.matchTemplate(image, template, cv2.TM_CCOEFF_NORMED)
                _, max_score, _, max_location = cv2.minMaxLoc(result)
                candidate = (
                    float(max_score),
                    (int(max_location[0]), int(max_location[1])),
                    scale,
                    width,
                    height,
                )
                if best is None or candidate[0] > best[0]:
                    best = candidate
            scale += self.scale_step

        if best is None:
            self.last_score = 0.0
            self.last_location = (0, 0)
            self.last_scale = 1.0
            return None

        score, max_location, best_scale, best_width, best_height = best
        self.last_score = score
        self.last_location = max_location
        self.last_scale = best_scale
        if score < self.threshold:
            return None

        left, top = max_location
        return Match(
            score=score,
            box=Region(
                left=int(left),
                top=int(top),
                width=best_width,
                height=best_height,
            ),
        )
