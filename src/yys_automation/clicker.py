from __future__ import annotations

import logging
import random

import pyautogui

from src.yys_automation.config import AppConfig, Region


class HumanLikeClicker:
    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        pyautogui.FAILSAFE = True

    def pick_point_inside(self, box: Region, rng: random.Random) -> tuple[int, int]:
        center_x = box.left + box.width // 2
        center_y = box.top + box.height // 2

        max_x = min(self.config.click_jitter_pixels.x, max(0, box.width // 2 - 1))
        max_y = min(self.config.click_jitter_pixels.y, max(0, box.height // 2 - 1))
        x = center_x + rng.randint(-max_x, max_x)
        y = center_y + rng.randint(-max_y, max_y)

        x = min(max(x, box.left), box.right - 1)
        y = min(max(y, box.top), box.bottom - 1)
        return x, y

    def click(self, x: int, y: int) -> None:
        duration = random.uniform(
            self.config.move_duration_seconds.min,
            self.config.move_duration_seconds.max,
        )
        self.logger.debug("Moving mouse to x=%d y=%d duration=%.3f", x, y, duration)
        pyautogui.moveTo(x, y, duration=duration)
        position = pyautogui.position()
        self.logger.info("Physical mouse positioned at x=%d y=%d", position.x, position.y)
        pyautogui.click()
        self.logger.info("Physical mouse click sent at x=%d y=%d", x, y)
