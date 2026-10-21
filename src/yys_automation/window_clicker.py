from __future__ import annotations

import logging
import random
import time

from src.yys_automation.config import AppConfig, Region
from src.yys_automation.window import WindowLocator


class WindowMessageClicker:
    """Send a click to the configured visible window without moving the cursor."""

    def __init__(self, config: AppConfig, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.locator = WindowLocator()

    def pick_point_inside(self, box: Region, rng: random.Random) -> tuple[int, int]:
        center_x = box.left + box.width // 2
        center_y = box.top + box.height // 2
        max_x = min(self.config.click_jitter_pixels.x, max(0, box.width // 2 - 1))
        max_y = min(self.config.click_jitter_pixels.y, max(0, box.height // 2 - 1))
        x = min(max(center_x + rng.randint(-max_x, max_x), box.left), box.right - 1)
        y = min(max(center_y + rng.randint(-max_y, max_y), box.top), box.bottom - 1)
        return x, y

    def click(self, x: int, y: int) -> None:
        import ctypes
        from ctypes import wintypes

        window = self.locator.find_first(self.config.window.title_contains)
        if window is None:
            raise RuntimeError(f"Window not found: {self.config.window.title_contains}")

        client_x = x - window.client_left
        client_y = y - window.client_top
        if not 0 <= client_x < window.client_width or not 0 <= client_y < window.client_height:
            raise ValueError(f"Point outside current window client area: x={x} y={y}")

        user32 = ctypes.windll.user32
        hwnd = wintypes.HWND(window.handle)
        lparam = (client_y << 16) | (client_x & 0xFFFF)
        down_ok = bool(user32.PostMessageW(hwnd, 0x0201, 0x0001, lparam))
        time.sleep(0.05)
        up_ok = bool(user32.PostMessageW(hwnd, 0x0202, 0x0000, lparam))
        if not down_ok or not up_ok:
            self.logger.error(
                "Window message click delivery uncertain: down_sent=%s up_sent=%s client=(%d,%d) hwnd=%s",
                down_ok, up_ok, client_x, client_y, window.handle,
            )
            raise RuntimeError(
                f"PostMessage click failed: down_sent={down_ok} up_sent={up_ok} "
                f"client=({client_x},{client_y}) hwnd={window.handle}"
            )
        self.logger.info(
            "Window click client=(x=%d y=%d) screen=(x=%d y=%d)",
            client_x,
            client_y,
            x,
            y,
        )
