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
        self._listener = keyboard.Listener(on_press=self._on_press, on_release=self._on_release)
        self._listener.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._listener is not None:
            self._listener.stop()

    def _on_press(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        self._pressed.add(key)
        if key == keyboard.Key.esc or self._is_ctrl_shift_q(key):
            self.logger.warning("Emergency stop requested")
            self._stop_event.set()
            return False

    def _on_release(self, key: keyboard.Key | keyboard.KeyCode) -> None:
        self._pressed.discard(key)

    def _is_ctrl_shift_q(self, key: keyboard.Key | keyboard.KeyCode) -> bool:
        if not isinstance(key, keyboard.KeyCode) or key.char is None:
            return False

        ctrl_pressed = keyboard.Key.ctrl_l in self._pressed or keyboard.Key.ctrl_r in self._pressed
        shift_pressed = keyboard.Key.shift_l in self._pressed or keyboard.Key.shift_r in self._pressed
        return ctrl_pressed and shift_pressed and key.char.lower() == "q"
