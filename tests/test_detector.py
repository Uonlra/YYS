from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.yys_automation.config import Region
from src.yys_automation.detector import TemplateDetector


class TemplateDetectorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.template = np.random.default_rng(42).integers(0, 256, (8, 10, 3), dtype=np.uint8)
        self.path = Path(self.temp.name) / "target.png"
        self.assertTrue(cv2.imwrite(str(self.path), self.template))

    def test_search_region_offsets_match_back_to_full_frame(self) -> None:
        image = np.random.default_rng(7).integers(0, 256, (60, 80, 3), dtype=np.uint8)
        image[35:43, 45:55] = self.template
        image[5:13, 5:15] = self.template

        detector = TemplateDetector(self.path, 0.99, 1.0, 1.0, 0.05, Region(35, 25, 40, 35))
        match = detector.find_best(image)

        self.assertIsNotNone(match)
        assert match is not None
        self.assertEqual(match.box, Region(45, 35, 10, 8))

    def test_scaled_templates_are_cached_between_frames(self) -> None:
        image = np.zeros((80, 80, 3), dtype=np.uint8)
        with patch("src.yys_automation.detector.cv2.resize", wraps=cv2.resize) as resize:
            detector = TemplateDetector(self.path, 0.8, 0.8, 1.2, 0.2)
            construction_calls = resize.call_count
            detector.find_best(image)
            detector.find_best(image)

        self.assertEqual(resize.call_count, construction_calls)
        self.assertEqual(len(detector._scaled_templates), 3)

    def test_fast_search_verifies_real_templates_at_scales_and_edges(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for name in ("start", "confirm", "reward"):
            for scale in (0.75, 1.0, 1.35):
                with self.subTest(name=name, scale=scale):
                    detector = TemplateDetector(root / "assets/targets" / f"{name}.png",
                                                0.86, scale, scale, coarse_to_fine=True)
                    template = detector._scaled_templates[0][1]
                    h, w = template.shape[:2]
                    for x, y in ((0, 0), (41, 53), (321 - w, 301 - h)):
                        image = np.random.default_rng(9).integers(0, 80, (301, 321, 3), dtype=np.uint8)
                        image[y:y+h, x:x+w] = template
                        match = detector.find_best(image)
                        self.assertIsNotNone(match, (name, scale, x, y))
                        self.assertEqual(match.box, Region(x, y, w, h))
                        self.assertGreater(match.score, 0.999)

    def test_fast_search_refines_roi_and_retains_small_template_fallback(self) -> None:
        image = np.zeros((60, 80, 3), dtype=np.uint8)
        image[35:43, 45:55] = self.template
        detector = TemplateDetector(self.path, 0.99, search_region=Region(35, 25, 40, 35),
                                    coarse_to_fine=True)
        self.assertEqual(detector.find_best(image).box, Region(45, 35, 10, 8))
        detector.search_region = Region(0, 0, 1, 1)
        self.assertIsNone(detector.find_best(image))

    def test_fast_search_offsets_large_template_inside_roi(self) -> None:
        root = Path(__file__).resolve().parents[1]
        detector = TemplateDetector(root / "assets/targets/start.png", 0.86,
                                    search_region=Region(17, 23, 301, 281), coarse_to_fine=True)
        h, w = detector.template.shape[:2]
        image = np.zeros((340, 360, 3), dtype=np.uint8)
        image[101:101+h, 81:81+w] = detector.template
        self.assertEqual(detector.find_best(image).box, Region(81, 101, w, h))

    def test_fast_coarse_hit_requires_original_resolution_score(self) -> None:
        # Opposite checkerboards average to the same coarse image, but differ at full resolution.
        base = np.random.default_rng(4).integers(70, 180, (16, 16, 3), dtype=np.uint8)
        template = np.repeat(np.repeat(base, 2, axis=0), 2, axis=1).astype(np.int16)
        checker = np.tile([[1, -1], [-1, 1]], (16, 16))[:, :, None] * 60
        cv2.imwrite(str(self.path), (template + checker).astype(np.uint8))
        image = np.zeros((80, 80, 3), dtype=np.uint8)
        image[20:52, 20:52] = (template - checker).astype(np.uint8)
        detector = TemplateDetector(self.path, 0.99, coarse_to_fine=True)
        self.assertIsNone(detector.find_best(image))


if __name__ == "__main__":
    unittest.main()
