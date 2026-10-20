from __future__ import annotations

import io
import logging
import tempfile
import unittest
from logging.handlers import RotatingFileHandler
from pathlib import Path
from unittest.mock import patch

from src.yys_automation.logging_setup import setup_logging


class LoggingSetupTests(unittest.TestCase):
    def setUp(self) -> None:
        temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(temp_dir.cleanup)
        self.log_file = Path(temp_dir.name) / "logs" / "automation.log"
        self.logger = logging.Logger("yys_automation")
        logger_patch = patch(
            "src.yys_automation.logging_setup.logging.getLogger", return_value=self.logger
        )
        logger_patch.start()
        self.addCleanup(logger_patch.stop)
        stderr_patch = patch("sys.stderr", new_callable=io.StringIO)
        self.console = stderr_patch.start()
        self.addCleanup(stderr_patch.stop)
        self.addCleanup(self.close_handlers)

    def close_handlers(self) -> None:
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
            handler.close()

    def test_rotation_configuration(self) -> None:
        logger = setup_logging(self.log_file)

        self.assertIs(logger, self.logger)
        self.assertEqual(logger.level, logging.INFO)
        self.assertFalse(logger.propagate)
        self.assertEqual(len(logger.handlers), 2)
        handler = next(h for h in logger.handlers if isinstance(h, RotatingFileHandler))
        self.assertEqual(handler.maxBytes, 5 * 1024 * 1024)
        self.assertEqual(handler.backupCount, 5)
        self.assertEqual(handler.mode, "a")
        self.assertEqual(handler.encoding, "utf-8")

    def test_rollover_keeps_only_five_archives_with_latest_records(self) -> None:
        logger = setup_logging(self.log_file)
        handler = next(h for h in logger.handlers if isinstance(h, RotatingFileHandler))
        handler.maxBytes = 200
        messages = [f"record-{index:02d} " + "x" * 120 for index in range(12)]

        for message in messages:
            logger.info(message)
        handler.flush()

        self.assertEqual(
            {path.name for path in self.log_file.parent.iterdir()},
            {"automation.log", *(f"automation.log.{index}" for index in range(1, 6))},
        )
        for index in range(6):
            path = self.log_file if index == 0 else Path(f"{self.log_file}.{index}")
            with self.subTest(path=path.name):
                lines = path.read_text(encoding="utf-8").splitlines()
                self.assertEqual(len(lines), 1)
                self.assertTrue(lines[0].endswith(f"INFO {messages[-1 - index]}"))
                self.assertLess(path.stat().st_size, handler.maxBytes)

    def test_reinitialization_closes_old_stream_and_avoids_duplicates(self) -> None:
        logger = setup_logging(self.log_file)
        old_handlers = logger.handlers[:]
        old_file_handler = next(h for h in old_handlers if isinstance(h, RotatingFileHandler))
        old_stream = old_file_handler.stream

        self.assertIs(setup_logging(self.log_file), logger)

        self.assertTrue(old_stream.closed)
        self.assertIsNone(old_file_handler.stream)
        self.assertEqual(len(logger.handlers), 2)
        self.assertTrue(all(h not in logger.handlers for h in old_handlers))
        logger.info("one record")
        self.assertEqual(self.log_file.read_text(encoding="utf-8").count("one record"), 1)
        self.assertEqual(self.console.getvalue().count("one record"), 1)

    def test_initialization_and_reinitialization_preserve_existing_utf8_content(self) -> None:
        self.log_file.parent.mkdir()
        original = "existing \u65e5\u5fd7\n"
        self.log_file.write_text(original, encoding="utf-8")

        logger = setup_logging(self.log_file)
        logger.info("first \u65e5\u5fd7")
        setup_logging(self.log_file).info("second \u65e5\u5fd7")

        content = self.log_file.read_text(encoding="utf-8")
        self.assertTrue(content.startswith(original))
        self.assertEqual(content.count("first \u65e5\u5fd7"), 1)
        self.assertEqual(content.count("second \u65e5\u5fd7"), 1)
        self.assertLess(content.index("first"), content.index("second"))


if __name__ == "__main__":
    unittest.main()
