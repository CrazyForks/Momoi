import tempfile
import unittest
from pathlib import Path

from momoi.channel.napcat import NapCatConfig
from momoi.config.models import AppConfig, HeartbeatConfig
from momoi.integrations.models import LLMConfig
from momoi.runtime import MomoiDaemon
from tests.support import provider_catalog


class HeartbeatStartupTest(unittest.IsolatedAsyncioTestCase):
    async def test_startup_requires_user_file_even_with_cached_guidance(self):
        for state in ("missing", "unset", "directory", "present", "empty", "disabled"):
            with self.subTest(state=state), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "HEARTBEAT.md"
                if state in ("present", "disabled"):
                    path.write_text("看看窗外。", encoding="utf-8")
                elif state == "empty":
                    path.touch()
                elif state == "directory":
                    path.mkdir()
                config = AppConfig(
                    providers=provider_catalog(LLMConfig(
                        "http://127.0.0.1", "test", "test", 100, 0, 1, 0,
                    )),
                    channel=NapCatConfig("ws://127.0.0.1", "20000", 1, 60, 30, 30, 20),
                    system_prompt="test",
                    transcript_turns_min=4,
                    transcript_turns_max=4,
                    episode_unsummarized_tail_turns=2,
                    memory_results=2,
                    database=Path(directory) / "momoi.sqlite3",
                    log_level="INFO",
                    heartbeat=HeartbeatConfig(enabled=state != "disabled"),
                    heartbeat_prompt="旧缓存不能代替用户文件",
                    heartbeat_prompt_path=None if state == "unset" else path,
                )
                missing = state in ("missing", "unset", "directory")
                if missing:
                    with self.assertLogs("momoi.runtime.daemon", level="WARNING") as logs:
                        daemon = MomoiDaemon(config)
                    self.assertIn("heartbeat_disabled_missing_prompt", " ".join(logs.output))
                else:
                    daemon = MomoiDaemon(config)
                try:
                    enabled = state in ("present", "empty")
                    self.assertEqual(daemon.config.heartbeat.enabled, enabled)
                    self.assertEqual(config.heartbeat.enabled, state != "disabled")
                    rendered = daemon._heartbeat_system_prompt()
                    self.assertNotIn("{{HEARTBEAT}}", rendered)
                    self.assertNotIn("旧缓存不能代替用户文件", rendered)
                    if state in ("present", "disabled"):
                        self.assertIn("看看窗外。", rendered)
                    # Persisted due work must also respect the startup decision.
                    daemon.store._db.execute(
                        "UPDATE self_state SET next_heartbeat_at=1 WHERE id=1"
                    )
                    claim = daemon.store.claim_due_heartbeat(
                        daemon.config.heartbeat, daemon.config.notifications,
                    )
                    self.assertEqual(claim is not None, enabled)
                finally:
                    daemon.store.close()
