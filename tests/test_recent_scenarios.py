from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from src.yys_automation.recent_scenarios import RECENT_LIMIT, RecentScenario, RecentScenarios


class RecentScenariosTests(unittest.TestCase):
    def setUp(self) -> None:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name).resolve()
        self.config = self.root / "config.yaml"

    def test_reopen_promotes_entry_and_history_is_bounded(self) -> None:
        history = RecentScenarios(self.config)
        for number in range(RECENT_LIMIT + 2):
            history.remember(self.root / f"{number}.yaml", f"step_{number}")
        older = self.root / "3.yaml"
        history.remember(older, "victory")
        loaded = RecentScenarios(self.config)
        self.assertEqual(len(loaded.entries), RECENT_LIMIT)
        self.assertEqual(loaded.entries[0], RecentScenario(older, "victory"))
        self.assertEqual(sum(item.path == older for item in loaded.entries), 1)
        self.assertEqual(RecentScenarios(self.root / "alternate.yaml").entries, [])

    def test_malformed_history_is_ignored(self) -> None:
        history = RecentScenarios(self.config)
        history.path.write_text("{incomplete", encoding="utf-8")
        self.assertEqual(RecentScenarios(self.config).entries, [])
        history.remember(self.root / "scenario.yaml", "start")
        self.assertEqual(RecentScenarios(self.config).entries[0].step_id, "start")

    def test_workspace_local_path_is_relative(self) -> None:
        history = RecentScenarios(self.config)
        scenario = self.root / "scenes" / "御魂.yaml"
        history.remember(scenario, "victory")
        data = json.loads(history.path.read_text(encoding="utf-8"))
        self.assertEqual(data["recent"][0]["path"], "scenes/御魂.yaml")
        self.assertEqual(RecentScenarios(self.config).entries, [RecentScenario(scenario, "victory")])
