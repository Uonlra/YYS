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


if __name__ == "__main__":
    unittest.main()
