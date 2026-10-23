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
        search_region: Region | None = None,
    ) -> None:
        template = cv2.imread(str(target_image), cv2.IMREAD_COLOR)
        if template is None:
            raise ValueError(f"Could not read target image: {target_image}")

        self.template = template
        self.threshold = threshold
        self.scale_min = scale_min
        self.scale_max = scale_max
        self.scale_step = scale_step
        self.search_region = search_region
        self.template_height, self.template_width = template.shape[:2]
        self._scaled_templates = self._build_scaled_templates()
        self.last_score = 0.0
        self.last_location = (0, 0)
        self.last_scale = 1.0

    def _build_scaled_templates(self) -> tuple[tuple[float, np.ndarray, int, int], ...]:
        templates: list[tuple[float, np.ndarray, int, int]] = []
        scale = self.scale_min
        while scale <= self.scale_max + self.scale_step / 10:
            width = max(1, round(self.template_width * scale))
            height = max(1, round(self.template_height * scale))
            if width == self.template_width and height == self.template_height:
                template = self.template
            else:
                template = cv2.resize(
                    self.template,
                    (width, height),
                    interpolation=cv2.INTER_AREA,
                )
            templates.append((scale, template, width, height))
            scale += self.scale_step
        return tuple(templates)

    def _reset_last_match(self) -> None:
        self.last_score = 0.0
        self.last_location = (0, 0)
        self.last_scale = 1.0

    def find_best(self, image: np.ndarray) -> Match | None:
        offset_left = 0
        offset_top = 0
        search_image = image
        if self.search_region is not None:
            offset_left = max(0, self.search_region.left)
            offset_top = max(0, self.search_region.top)
            right = min(image.shape[1], self.search_region.right)
            bottom = min(image.shape[0], self.search_region.bottom)
            if right <= offset_left or bottom <= offset_top:
                self._reset_last_match()
                return None
            search_image = image[offset_top:bottom, offset_left:right]

        best: tuple[float, tuple[int, int], float, int, int] | None = None
        for scale, template, width, height in self._scaled_templates:
            if width <= search_image.shape[1] and height <= search_image.shape[0]:
                result = cv2.matchTemplate(search_image, template, cv2.TM_CCOEFF_NORMED)
                _, max_score, _, max_location = cv2.minMaxLoc(result)
                candidate = (
                    float(max_score),
                    (int(max_location[0] + offset_left), int(max_location[1] + offset_top)),
                    scale,
                    width,
                    height,
                )
                if best is None or candidate[0] > best[0]:
                    best = candidate

        if best is None:
            self._reset_last_match()
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
