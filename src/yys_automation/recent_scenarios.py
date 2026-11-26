"""Local workbench history for one global configuration file."""
from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


RECENT_LIMIT = 8


@dataclass(frozen=True)
class RecentScenario:
    path: Path
    step_id: str | None = None


class RecentScenarios:
    def __init__(self, config_path: Path) -> None:
        config_path = config_path.resolve()
        self.path = config_path.with_name(f".{config_path.name}.yys-workbench.json")
        self.entries = self._read() or []

    def _read(self) -> list[RecentScenario] | None:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if not isinstance(data, dict) or data.get("version") != 1 or not isinstance(data.get("recent"), list):
            return None
        entries = []
        for entry in data["recent"][:RECENT_LIMIT]:
            if not isinstance(entry, dict):
                continue
            value = entry.get("path")
            if not isinstance(value, str) or not value.strip() or "\0" in value:
                continue
            step_id = entry.get("step_id")
            try:
                path = (self.path.parent / value).resolve()
            except (OSError, ValueError, RuntimeError):
                continue
            if all(item.path != path for item in entries):
                entries.append(RecentScenario(path, step_id if isinstance(step_id, str) else None))
        return entries

    def selected_step(self, path: Path) -> str | None:
        return next((item.step_id for item in self.entries if item.path == path), None)

    def remember(self, path: Path, step_id: str | None, *, replaced_path: Path | None = None) -> bool:
        """Update the session history and try to save it without blocking the editor on errors."""
        current = RecentScenario(path, step_id)
        on_disk = self._read()
        previous = self.entries if on_disk is None else on_disk
        history = [current]
        for item in previous:
            if item.path != replaced_path and all(existing.path != item.path for existing in history):
                history.append(item)
        self.entries = history[:RECENT_LIMIT]
        if self.entries == on_disk:
            return True
        return self._write()

    def _write(self) -> bool:
        data = []
        for entry in self.entries:
            # Keep project-local history portable when the project directory moves.
            path = entry.path.relative_to(self.path.parent) if entry.path.is_relative_to(self.path.parent) else entry.path
            data.append({"path": path.as_posix(), "step_id": entry.step_id})
        draft = None
        try:
            fd, name = tempfile.mkstemp(prefix=".yys-workbench-", suffix=".tmp", dir=self.path.parent)
            draft = Path(name)
            with os.fdopen(fd, "w", encoding="utf-8") as output:
                json.dump({"version": 1, "recent": data}, output, ensure_ascii=False, indent=2)
                output.write("\n")
            os.replace(draft, self.path)
            return True
        except OSError:
            return False
        finally:
            if draft is not None:
                try:
                    draft.unlink(missing_ok=True)
                except OSError:
                    pass
