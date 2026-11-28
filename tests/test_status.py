import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

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

    @unittest.skipUnless(sys.platform == "win32", "requires Windows file sharing rules")
    def test_update_retries_when_a_reader_temporarily_holds_the_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status = RunStatus(Path(directory) / "status.json")
            status.update(state="running", clicks=2)
            with status.path.open(encoding="utf-8") as reader, patch(
                "src.yys_automation.status.sleep", side_effect=lambda _delay: reader.close()
            ) as pause:
                status.update(activity="no_match")

            pause.assert_called_once()
            self.assertEqual(status.read()["activity"], "no_match")
            self.assertEqual(status.read()["clicks"], 2)
            self.assertEqual(list(status.path.parent.iterdir()), [status.path])

    @unittest.skipUnless(sys.platform == "win32", "requires Windows file sharing rules")
    def test_busy_snapshot_preserves_the_previous_file_after_bounded_retries(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            status = RunStatus(Path(directory) / "status.json")
            status.update(state="running")
            with status.path.open(encoding="utf-8"), patch("src.yys_automation.status.sleep") as pause:
                with self.assertRaises(PermissionError):
                    status.update(activity="no_match")

            self.assertEqual(pause.call_count, 3)
            self.assertNotIn("activity", status.read())
            self.assertEqual(list(status.path.parent.iterdir()), [status.path])
            status.update(state="completed")
            self.assertEqual(status.read()["activity"], "no_match")


if __name__ == "__main__":
    unittest.main()
