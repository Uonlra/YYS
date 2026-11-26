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
        *,
        coarse_to_fine: bool = False,
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
        self.coarse_to_fine = coarse_to_fine
        self._coarse_templates = tuple(
            cv2.resize(item[1], None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
            if min(item[2], item[3]) >= 16 else item[1]
            for item in self._scaled_templates
        ) if coarse_to_fine else ()
        self.last_score = 0.0
        self.last_location = (0, 0)
        self.last_scale = 1.0
        self.last_box: Region | None = None

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
        self.last_box = None

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
        coarse_image = None
        if self.coarse_to_fine and min(search_image.shape[:2]) >= 16:
            # Pad odd dimensions so right/bottom edge candidates remain searchable.
            coarse_source = cv2.copyMakeBorder(
                search_image, 0, search_image.shape[0] % 2, 0, search_image.shape[1] % 2,
                cv2.BORDER_REPLICATE,
            )
            coarse_image = cv2.resize(coarse_source, None, fx=0.5, fy=0.5, interpolation=cv2.INTER_AREA)
        for index, (scale, template, width, height) in enumerate(self._scaled_templates):
            if width <= search_image.shape[1] and height <= search_image.shape[0]:
                if coarse_image is not None and min(width, height) >= 16:
                    found = self._refine_candidates(search_image, coarse_image, template,
                                                    self._coarse_templates[index], width, height)
                    if found is None:
                        continue
                    max_score, max_location = found
                else:
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
        self.last_box = Region(*max_location, best_width, best_height)
        if score < self.threshold:
            return None

        return Match(score, self.last_box)

    def _refine_candidates(
        self, image: np.ndarray, coarse_image: np.ndarray,
        template: np.ndarray, coarse_template: np.ndarray, width: int, height: int,
    ) -> tuple[float, tuple[int, int]] | None:
        """Propose at half resolution; only original BGR scores authorize a click.

        This is an opt-in approximate search: a candidate lost to downsampling or
        outside the five strongest coarse peaks can be missed. Small templates
        use exhaustive matching instead.
        """
        if (coarse_template.shape[0] > coarse_image.shape[0]
                or coarse_template.shape[1] > coarse_image.shape[1]):
            return None
        result = cv2.matchTemplate(coarse_image, coarse_template, cv2.TM_CCOEFF_NORMED)
        best = None
        for _ in range(5):
            _, score, _, (x, y) = cv2.minMaxLoc(result)
            if score < min(0.6, self.threshold - 0.2):
                break
            left, top = max(0, x * 2 - 4), max(0, y * 2 - 4)
            right = min(image.shape[1], x * 2 + width + 5)
            bottom = min(image.shape[0], y * 2 + height + 5)
            refined = cv2.matchTemplate(image[top:bottom, left:right], template, cv2.TM_CCOEFF_NORMED)
            _, full_score, _, location = cv2.minMaxLoc(refined)
            if best is None or full_score > best[0]:
                best = (float(full_score), (location[0] + left, location[1] + top))
            # Suppress this neighbourhood, leaving other candidate positions.
            result[max(0, y - 4):y + 5, max(0, x - 4):x + 5] = -1
        return best
