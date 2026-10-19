from __future__ import annotations

import ctypes
from ctypes import wintypes

import cv2
import numpy as np

from src.yys_automation.window import WindowInfo


class WindowCaptureError(RuntimeError):
    pass


def capture_client(window: WindowInfo) -> tuple[np.ndarray, str]:
    """Capture a window client area with PrintWindow without moving the mouse."""
    if window.client_width <= 0 or window.client_height <= 0:
        raise WindowCaptureError("Window client area is empty")

    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    hwnd = wintypes.HWND(window.handle)
    width, height = window.client_width, window.client_height

    window_dc = user32.GetDC(hwnd)
    if not window_dc:
        raise WindowCaptureError("GetDC failed")
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    if not memory_dc or not bitmap:
        if memory_dc:
            gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)
        raise WindowCaptureError("Could not allocate capture bitmap")

    old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
    try:
        # PW_CLIENTONLY asks Windows for the client area rather than title bar.
        method = "PrintWindow"
        captured = bool(user32.PrintWindow(hwnd, memory_dc, 1))
        if not captured:
            # Some visible GPU windows reject PrintWindow but still expose a
            # client DC. BitBlt is a visible-window fallback; it is not expected
            # to work for minimized or fully occluded windows.
            srccopy = 0x00CC0020
            captureblt = 0x40000000
            captured = bool(
                gdi32.BitBlt(
                    memory_dc,
                    0,
                    0,
                    width,
                    height,
                    window_dc,
                    0,
                    0,
                    srccopy | captureblt,
                )
            )
            method = "BitBlt"
        if not captured:
            raise WindowCaptureError("PrintWindow and BitBlt both failed")

        class BitmapInfoHeader(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", wintypes.LONG),
                ("biHeight", wintypes.LONG),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", wintypes.LONG),
                ("biYPelsPerMeter", wintypes.LONG),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BitmapInfo(ctypes.Structure):
            _fields_ = [("bmiHeader", BitmapInfoHeader), ("bmiColors", wintypes.DWORD * 3)]

        info = BitmapInfo()
        info.bmiHeader.biSize = ctypes.sizeof(BitmapInfoHeader)
        info.bmiHeader.biWidth = width
        info.bmiHeader.biHeight = -height  # top-down output
        info.bmiHeader.biPlanes = 1
        info.bmiHeader.biBitCount = 32
        info.bmiHeader.biCompression = 0  # BI_RGB

        pixels = np.empty((height, width, 4), dtype=np.uint8)
        copied = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            ctypes.c_void_p(pixels.ctypes.data),
            ctypes.byref(info),
            0,
        )
        if copied != height:
            raise WindowCaptureError(f"GetDIBits copied {copied} rows, expected {height}")

        return cv2.cvtColor(pixels, cv2.COLOR_BGRA2BGR), method
    finally:
        gdi32.SelectObject(memory_dc, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(hwnd, window_dc)


def save_capture(window: WindowInfo, output_path: str) -> str:
    image, method = capture_client(window)
    if not cv2.imwrite(output_path, image):
        raise WindowCaptureError(f"Could not write capture: {output_path}")
    return method
