from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class RunStatus:
    """Small atomic JSON status file for the GUI and external monitors."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._payload: dict[str, Any] = {}

    def update(self, **values: Any) -> None:
        payload = {
            **self._payload,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            **values,
        }
        self._payload = payload
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=self.path.name + ".", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as file:
                json.dump(payload, file, ensure_ascii=False, indent=2)
                file.write("\n")
            os.replace(name, self.path)
        finally:
            if os.path.exists(name):
                os.unlink(name)

    def read(self) -> dict[str, Any] | None:
        try:
            with self.path.open("r", encoding="utf-8") as file:
                value = json.load(file)
            return value if isinstance(value, dict) else None
        except (OSError, ValueError):
            return None
