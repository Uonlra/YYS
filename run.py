from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

from src.yys_automation.config import AppConfig, load_config
from src.yys_automation.logging_setup import setup_logging
from src.yys_automation.window import WindowLocator


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local desktop UI automation MVP")
    parser.add_argument(
        "--config",
        default="config.yaml",
        help="Path to YAML config file. Defaults to config.yaml.",
    )
    parser.add_argument(
        "--probe-window",
        action="store_true",
        help="Locate the configured Windows window and print its client area without clicking.",
    )
    return parser.parse_args()


def sleep_with_stop(seconds: float, stop_controller: StopController) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not stop_controller.should_stop:
        time.sleep(min(0.05, deadline - time.monotonic()))


def run(config: AppConfig) -> int:
    from src.yys_automation.clicker import HumanLikeClicker
    from src.yys_automation.detector import TemplateDetector
    from src.yys_automation.safety import StopController
    from src.yys_automation.screen import ScreenCapture

    logger = setup_logging(config.log_file)
    stop_controller = StopController(logger)
    stop_controller.start()

    detector = TemplateDetector(config.target_image, config.threshold)
    screen = ScreenCapture(config.allowed_region)
    clicker = HumanLikeClicker(config, logger)

    logger.info("Automation starting. Press Esc or Ctrl+Shift+Q to stop.")
    logger.info("Config: target=%s threshold=%.3f dry_run=%s", config.target_image, config.threshold, config.dry_run)

    if config.startup_delay_seconds > 0:
        logger.info("Startup delay: %.1f seconds", config.startup_delay_seconds)
        sleep_with_stop(config.startup_delay_seconds, stop_controller)

    clicks_done = 0
    last_click_at = 0.0

    try:
        while not stop_controller.should_stop:
            frame = screen.grab()
            match = detector.find_best(frame.image)

            if match is None:
                logger.debug("No match found")
                sleep_with_stop(config.scan_interval_seconds, stop_controller)
                continue

            absolute_box = match.box.offset(frame.left, frame.top)
            logger.info(
                "Match score=%.4f box=(left=%d top=%d width=%d height=%d)",
                match.score,
                absolute_box.left,
                absolute_box.top,
                absolute_box.width,
                absolute_box.height,
            )

            now = time.monotonic()
            if now - last_click_at < config.min_click_interval_seconds:
                logger.info("Click skipped: cooldown active")
                sleep_with_stop(config.scan_interval_seconds, stop_controller)
                continue

            if config.max_clicks is not None and clicks_done >= config.max_clicks:
                logger.info("Max clicks reached: %d", config.max_clicks)
                break

            x, y = clicker.pick_point_inside(absolute_box, random.Random())
            if not config.allowed_region.contains_point(x, y):
                logger.warning("Click skipped: point outside allowed region x=%d y=%d", x, y)
                sleep_with_stop(config.scan_interval_seconds, stop_controller)
                continue

            if config.dry_run:
                logger.info("Dry run: would click x=%d y=%d", x, y)
            else:
                clicker.click(x, y)
                clicks_done += 1
                last_click_at = time.monotonic()
                logger.info("Clicked x=%d y=%d total_clicks=%d", x, y, clicks_done)

            sleep_with_stop(config.scan_interval_seconds, stop_controller)
    except KeyboardInterrupt:
        logger.info("Stopped by KeyboardInterrupt")
    finally:
        stop_controller.stop()
        logger.info("Automation stopped. total_clicks=%d", clicks_done)

    return 0


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        print("Copy config.example.yaml to config.yaml and edit it first.", file=sys.stderr)
        return 2

    config = load_config(config_path)
    if args.probe_window:
        window = WindowLocator().find_first(config.window.title_contains)
        if window is None:
            print(f"Window not found: {config.window.title_contains}")
            return 1
        print(
            f"Window: {window.title}\n"
            f"Handle: {window.handle}\n"
            f"Client: left={window.client_left} top={window.client_top} "
            f"width={window.client_width} height={window.client_height}"
        )
        return 0
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
