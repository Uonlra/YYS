import tempfile
import unittest
from pathlib import Path

from src.yys_automation.status import RunStatus


class RunStatusTests(unittest.TestCase):
    def test_update_writes_readable_atomic_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status = RunStatus(Path(directory) / "status.json")
            status.update(state="running", clicks=2, current_step="reward")
            status.update(last_step_duration_seconds=1.25)
            self.assertEqual(status.read()["current_step"], "reward")
            self.assertEqual(status.read()["clicks"], 2)
            self.assertEqual(status.read()["last_step_duration_seconds"], 1.25)

    def test_read_returns_none_for_missing_or_invalid_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status = RunStatus(Path(directory) / "status.json")
            self.assertIsNone(status.read())
            status.path.write_text("not json", encoding="utf-8")
            self.assertIsNone(status.read())


if __name__ == "__main__":
    unittest.main()
