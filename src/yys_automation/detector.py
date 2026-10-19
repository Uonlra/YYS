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
    def __init__(self, target_image: Path, threshold: float) -> None:
        template = cv2.imread(str(target_image), cv2.IMREAD_COLOR)
        if template is None:
            raise ValueError(f"Could not read target image: {target_image}")

        self.template = template
        self.threshold = threshold
        self.template_height, self.template_width = template.shape[:2]

    def find_best(self, image: np.ndarray) -> Match | None:
        if image.shape[0] < self.template_height or image.shape[1] < self.template_width:
            return None

        result = cv2.matchTemplate(image, self.template, cv2.TM_CCOEFF_NORMED)
        _, max_score, _, max_location = cv2.minMaxLoc(result)
        score = float(max_score)
        if score < self.threshold:
            return None

        left, top = max_location
        return Match(
            score=score,
            box=Region(
                left=int(left),
                top=int(top),
                width=self.template_width,
                height=self.template_height,
            ),
        )
