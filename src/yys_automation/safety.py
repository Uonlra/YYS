from __future__ import annotations

import logging
from dataclasses import dataclass, field
from threading import Event

from pynput import keyboard


@dataclass
class StopController:
    logger: logging.Logger
    _stop_event: Event = field(default_factory=Event)
    _listener: keyboard.Listener | None = None
    _pressed: set[keyboard.Key | keyboard.KeyCode] = field(default_factory=set)

    @property
    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    def start(self) -> None:
        if self._listener is not None and self._listener.is_alive():
            return
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._listener is not None:
            self._listener.stop()
            if self._listener.is_alive():
                self._listener.join(timeout=2)
            self._listener = None

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode) -> bool | None:
        self._pressed.add(key)
        if self._is_ctrl_shift_q(key):
            self.logger.warning("Emergency stop requested")
            self._stop_event.set()
            return False
        return None

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        self._pressed.discard(key)

    def _is_ctrl_shift_q(self, key: keyboard.Key | keyboard.KeyCode) -> bool:
        if not isinstance(key, keyboard.KeyCode):
            return False

        # Windows may translate Ctrl+Shift+Q to a control character.
        is_q = key.vk == ord("Q") or (key.char or "").lower() == "q"
        ctrl_pressed = self._pressed & {keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r}
        shift_pressed = self._pressed & {keyboard.Key.shift_l, keyboard.Key.shift_r}
        return is_q and bool(ctrl_pressed) and bool(shift_pressed)
