from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class WindowInfo:
    handle: int
    title: str
    client_left: int
    client_top: int
    client_width: int
    client_height: int


class WindowLocator:
    """Locate a visible Windows window and expose its client-area geometry."""

    def find_first(self, title_contains: str) -> WindowInfo | None:
        try:
            import ctypes
            from ctypes import wintypes
        except ImportError as exc:  # pragma: no cover - only relevant off Windows
            raise RuntimeError("Window mode requires Windows") from exc

        user32 = ctypes.windll.user32
        matches: list[WindowInfo] = []

        @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        def callback(hwnd: int, _lparam: int) -> bool:
            if not user32.IsWindowVisible(hwnd):
                return True
            length = user32.GetWindowTextLengthW(hwnd)
            if length <= 0:
                return True
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buffer, length + 1)
            title = buffer.value
            if title_contains.lower() not in title.lower():
                return True

            rect = wintypes.RECT()
            if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
                return True
            client_width = int(rect.right - rect.left)
            client_height = int(rect.bottom - rect.top)
            # Minimized windows commonly report a -32000 position and zero-sized
            # client area; they are not usable for capture or coordinate mapping.
            if client_width <= 0 or client_height <= 0:
                return True
            point = wintypes.POINT(0, 0)
            if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
                return True
            matches.append(
                WindowInfo(
                    handle=int(hwnd),
                    title=title,
                    client_left=int(point.x),
                    client_top=int(point.y),
                    client_width=client_width,
                    client_height=client_height,
                )
            )
            return True

        user32.EnumWindows(callback, 0)
        return matches[0] if matches else None


@dataclass(frozen=True)
class CoordinateMapper:
    reference_width: int
    reference_height: int
    actual_width: int
    actual_height: int

    def to_actual(self, x: int, y: int) -> tuple[int, int]:
        if self.reference_width <= 0 or self.reference_height <= 0:
            raise ValueError("reference dimensions must be positive")
        actual_x = round(x * self.actual_width / self.reference_width)
        actual_y = round(y * self.actual_height / self.reference_height)
        return (
            min(max(actual_x, 0), max(self.actual_width - 1, 0)),
            min(max(actual_y, 0), max(self.actual_height - 1, 0)),
        )
