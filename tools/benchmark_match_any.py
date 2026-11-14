"""Offline comparison; never captures a window or sends clicks.

Run from the project root:
    python tools/benchmark_match_any.py --frames logs/failures --limit 5
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import statistics
import sys
import time

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.yys_automation.config import load_config
from src.yys_automation.detector import TemplateDetector
from src.yys_automation.scenario import load_scenario


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=ROOT / "config.yaml")
    parser.add_argument("--scenario", type=Path, default=ROOT / "YYSscript/yuhun/scenario.match-any.yaml")
    parser.add_argument("--frames", type=Path)
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--repeats", type=int, default=1)
    args = parser.parse_args()
    if args.limit < 1 or args.repeats < 1:
        parser.error("limit and repeats must be positive")
    config = load_config(args.config)
    scenario = load_scenario(args.scenario)
    detectors = {
        mode: [(step.id, TemplateDetector(
            step.image, step.threshold if step.threshold is not None else config.threshold,
            config.template_scale_min, config.template_scale_max, config.template_scale_step,
            config.allowed_region if config.capture_mode == "window" else None,
            coarse_to_fine=(mode == "coarse_to_fine"),
        )) for step in scenario.steps]
        for mode in ("exhaustive", "coarse_to_fine")
    }
    frames = []
    if args.frames:
        for path in sorted(args.frames.glob("*.png"))[-args.limit:]:
            image = cv2.imread(str(path))
            if image is None:
                raise ValueError(f"Cannot decode {path}")
            frames.append((path.name, image))
    # Controlled positive cases cover scale extremes and odd pixel coordinates.
    for scale in (config.template_scale_min, 1.0, config.template_scale_max):
        image = np.random.default_rng(42).integers(
            0, 80, (config.window.reference_height, config.window.reference_width, 3), dtype=np.uint8,
        )
        for i, (_, detector) in enumerate(detectors["exhaustive"]):
            template = cv2.resize(detector.template, (
                round(detector.template_width * scale), round(detector.template_height * scale),
            ), interpolation=cv2.INTER_AREA)
            h, w = template.shape[:2]
            x, y = 51 + i * (image.shape[1] // len(scenario.steps)), 101
            if x + w > image.shape[1] or y + h > image.shape[0]:
                raise ValueError("Synthetic layout does not fit the reference size")
            image[y:y+h, x:x+w] = template
        frames.append((f"synthetic_scale_{scale:.2f}", image))
    timings = {mode: [] for mode in detectors}
    rows = []
    for name, image in frames:
        row = {"frame": name}
        for mode, items in detectors.items():
            results = []
            for _ in range(args.repeats):
                started = time.perf_counter()
                results = [(key, detector.find_best(image)) for key, detector in items]
                timings[mode].append(time.perf_counter() - started)
            row[mode] = [
                {"target": key, "score": round(match.score, 5),
                 "box": [match.box.left, match.box.top, match.box.width, match.box.height]}
                for key, match in results if match is not None
            ]
        rows.append(row)
    means = {mode: round(statistics.mean(values), 4) for mode, values in timings.items()}
    print(json.dumps({
        "opencv": cv2.__version__, "opencv_threads": cv2.getNumThreads(),
        "repeats": args.repeats, "mean_scan_seconds": means,
        "speedup": round(means["exhaustive"] / means["coarse_to_fine"], 2),
        "frames": rows,
    }, indent=2))


if __name__ == "__main__":
    main()
