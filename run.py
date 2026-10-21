from __future__ import annotations

import argparse
import random
import sys
import time
from pathlib import Path

import yaml

from src.yys_automation.config import AppConfig, Region, load_config
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
    parser.add_argument(
        "--capture-window",
        metavar="PATH",
        help="Capture the configured window client area to PATH without clicking.",
    )
    parser.add_argument(
        "--diagnose-match",
        action="store_true",
        help="Capture once and print the best template score without clicking.",
    )
    parser.add_argument(
        "--validate-scenario",
        metavar="PATH",
        help="Validate a scenario YAML without running it.",
    )
    parser.add_argument(
        "--scenario",
        metavar="PATH",
        help="Run a scenario YAML through the workflow state machine.",
    )
    parser.add_argument(
        "--gui",
        nargs="?",
        const="scenario.yaml",
        metavar="PATH",
        help="Open the visual scenario editor, optionally for PATH.",
    )
    return parser.parse_args()


def sleep_with_stop(seconds: float, stop_controller: StopController) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline and not stop_controller.should_stop:
        time.sleep(max(0, min(0.05, deadline - time.monotonic())))


def run(config: AppConfig) -> int:
    from src.yys_automation.clicker import HumanLikeClicker
    from src.yys_automation.detector import TemplateDetector
    from src.yys_automation.safety import StopController
    from src.yys_automation.screen import ScreenCapture
    from src.yys_automation.window_screen import WindowScreenCapture

    logger = setup_logging(config.log_file)
    stop_controller = StopController(logger)
    clicks_done = 0
    last_click_at = 0.0
    last_diagnostic_at = 0.0
    screen = None

    try:
        detector = TemplateDetector(
            config.target_image,
            config.threshold,
            config.template_scale_min,
            config.template_scale_max,
            config.template_scale_step,
        )
        screen = (
            WindowScreenCapture(config.window)
            if config.capture_mode == "window"
            else ScreenCapture(config.allowed_region)
        )
        clicker = HumanLikeClicker(config, logger)
        stop_controller.start()

        logger.info("Automation starting. Press Esc or Ctrl+Shift+Q to stop.")
        logger.info(
            "Config: target=%s threshold=%.3f dry_run=%s capture_mode=%s",
            config.target_image,
            config.threshold,
            config.dry_run,
            config.capture_mode,
        )

        if config.startup_delay_seconds > 0:
            logger.info("Startup delay: %.1f seconds", config.startup_delay_seconds)
            sleep_with_stop(config.startup_delay_seconds, stop_controller)

        while not stop_controller.should_stop:
            try:
                frame = screen.grab()
            except Exception as exc:  # keep the stop hotkey available on capture errors
                logger.error("Capture failed: %s", exc)
                sleep_with_stop(config.scan_interval_seconds, stop_controller)
                continue
            match = detector.find_best(frame.image)

            if match is None:
                now = time.monotonic()
                if now - last_diagnostic_at >= 2.0:
                    last_diagnostic_at = now
                    logger.info(
                        "No match: best_score=%.4f threshold=%.4f scale=%.3f "
                        "best_location=(left=%d top=%d) frame=(left=%d top=%d width=%d height=%d)",
                        detector.last_score,
                        detector.threshold,
                        detector.last_scale,
                        detector.last_location[0],
                        detector.last_location[1],
                        frame.left,
                        frame.top,
                        round(frame.image.shape[1] * frame.scale_x),
                        round(frame.image.shape[0] * frame.scale_y),
                    )
                sleep_with_stop(config.scan_interval_seconds, stop_controller)
                continue

            absolute_box = frame.to_screen_region(match.box)
            logger.info(
                "Frame client=(left=%d top=%d width=%d height=%d) "
                "reference=(width=%d height=%d) scale=(x=%.4f y=%.4f)",
                frame.left,
                frame.top,
                round(frame.image.shape[1] * frame.scale_x),
                round(frame.image.shape[0] * frame.scale_y),
                frame.image.shape[1],
                frame.image.shape[0],
                frame.scale_x,
                frame.scale_y,
            )
            logger.info(
                "Match score=%.4f reference_box=(left=%d top=%d width=%d height=%d) "
                "screen_box=(left=%d top=%d width=%d height=%d)",
                match.score,
                match.box.left,
                match.box.top,
                match.box.width,
                match.box.height,
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
            frame_region = config.allowed_region
            if config.capture_mode == "window":
                frame_region = frame.to_screen_region(config.allowed_region)
            if not frame_region.contains_point(x, y):
                logger.warning("Click skipped: point outside allowed region x=%d y=%d", x, y)
                sleep_with_stop(config.scan_interval_seconds, stop_controller)
                continue

            if config.dry_run:
                clicks_done += 1
                last_click_at = time.monotonic()
                logger.info("Dry run: would click x=%d y=%d", x, y)
                logger.info("Dry run action count=%d", clicks_done)
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
        if isinstance(screen, ScreenCapture):
            screen.close()
        logger.info("Automation stopped. total_clicks=%d", clicks_done)

    return 0


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    if not config_path.exists():
        print(f"Config file not found: {config_path}", file=sys.stderr)
        print("Copy config.example.yaml to config.yaml and edit it first.", file=sys.stderr)
        return 2

    try:
        config = load_config(config_path)
    except (OSError, ValueError, KeyError, TypeError, yaml.YAMLError) as exc:
        print(f"Invalid config: {exc}", file=sys.stderr)
        return 2
    if args.gui is not None:
        from src.yys_automation.config_gui import launch_gui

        launch_gui(Path(args.gui), config_path)
        return 0
    if args.validate_scenario:
        from src.yys_automation.scenario import load_scenario, validate_scenario

        scenario_path = Path(args.validate_scenario)
        errors = validate_scenario(scenario_path, config)
        if errors:
            print("Scenario invalid:")
            for error in errors:
                print(f"- {error}")
            return 1
        scenario = load_scenario(scenario_path)
        click_budget, budget_source = scenario.click_budget(config)
        if scenario.execution_mode == "match_any":
            print(
                f"Scenario valid: {scenario.name} execution_mode=match_any targets={len(scenario.steps)} "
                f"max_clicks={click_budget if click_budget is not None else 'unlimited'} budget_source={budget_source}"
            )
            return 0
        print(
            f"Scenario valid: {scenario.name} steps={len(scenario.steps)} "
            f"cycles={scenario.cycle_limit} retries={scenario.max_retries} "
            f"clicks_per_cycle={scenario.clicks_per_cycle} "
            f"max_attempts_per_cycle={scenario.click_attempts_per_cycle} "
            f"max_clicks={click_budget if click_budget is not None else 'unlimited'} "
            f"budget_source={budget_source}"
        )
        return 0
    if args.scenario:
        from src.yys_automation.scenario import load_scenario, validate_scenario
        from src.yys_automation.safety import StopController
        from src.yys_automation.window_screen import WindowScreenCapture
        from src.yys_automation.workflow import WorkflowRunner
        from src.yys_automation.clicker import HumanLikeClicker
        from src.yys_automation.window_clicker import WindowMessageClicker

        if config.capture_mode != "window":
            print("Scenario mode requires capture_mode: window")
            return 2
        scenario_path = Path(args.scenario)
        errors = validate_scenario(scenario_path, config)
        if errors:
            print("Scenario invalid:")
            for error in errors:
                print(f"- {error}")
            return 1
        scenario = load_scenario(scenario_path)
        logger = setup_logging(config.log_file)
        stop_controller = StopController(logger)
        source = WindowScreenCapture(config.window)
        clicker = (
            HumanLikeClicker(config, logger)
            if scenario.execution_mode == "match_any"
            else WindowMessageClicker(config, logger)
        )
        try:
            stop_controller.start()
            logger.info(
                "Click backend: %s",
                "pyautogui physical mouse" if scenario.execution_mode == "match_any" else "window messages",
            )
            return 0 if WorkflowRunner(
                scenario,
                config,
                source,
                clicker,
                stop_controller,
                logger,
            ).run() else 1
        finally:
            stop_controller.stop()
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
    if args.capture_window:
        from src.yys_automation.window_capture import WindowCaptureError, save_capture

        window = WindowLocator().find_first(config.window.title_contains)
        if window is None:
            print(f"Window not found: {config.window.title_contains}")
            return 1
        try:
            method = save_capture(window, args.capture_window)
        except WindowCaptureError as exc:
            print(f"Window capture failed: {exc}")
            return 1
        print(
            f"Captured {window.client_width}x{window.client_height} client area "
            f"to {args.capture_window} using {method}"
        )
        return 0
    if args.diagnose_match:
        from src.yys_automation.detector import TemplateDetector
        from src.yys_automation.window_screen import WindowScreenCapture

        if config.capture_mode != "window":
            print("--diagnose-match currently requires capture_mode: window")
            return 2
        try:
            frame = WindowScreenCapture(config.window).grab()
        except Exception as exc:
            print(f"Window capture failed: {exc}")
            return 1
        detector = TemplateDetector(
            config.target_image,
            config.threshold,
            config.template_scale_min,
            config.template_scale_max,
            config.template_scale_step,
        )
        match = detector.find_best(frame.image)
        print(
            f"best_score={detector.last_score:.4f} threshold={detector.threshold:.4f} "
            f"template_scale={detector.last_scale:.3f} "
            f"best_location=(left={detector.last_location[0]} top={detector.last_location[1]}) "
            f"frame={frame.image.shape[1]}x{frame.image.shape[0]} "
            f"client={round(frame.image.shape[1] * frame.scale_x)}x{round(frame.image.shape[0] * frame.scale_y)}"
        )
        if match is not None:
            box = frame.to_screen_region(match.box)
            print(
                f"matched reference_box=({match.box.left},{match.box.top},"
                f"{match.box.width},{match.box.height}) "
                f"screen_box=({box.left},{box.top},{box.width},{box.height})"
            )
        return 0
    return run(config)


if __name__ == "__main__":
    raise SystemExit(main())
