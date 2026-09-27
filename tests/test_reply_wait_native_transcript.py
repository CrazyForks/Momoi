from tests.support import provider_catalog
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from momoi.channel.napcat import NapCatConfig
from momoi.config.models import AppConfig
from momoi.integrations.models import LLMConfig
from momoi.models import AgentReply, IncomingMessage
from momoi.runtime import MomoiDaemon


class ReplyWaitNativeTranscriptTest(unittest.IsolatedAsyncioTestCase):
    async def test_followup_continues_after_native_shared_conversation(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            daemon = MomoiDaemon(
                AppConfig(
                    providers=provider_catalog(LLMConfig("http://127.0.0.1", "test", "test", 100, 0, 1, 0)),
                    channel=NapCatConfig(
                        "ws://127.0.0.1", "20000", 1, 60, 30, 30, 20
                    ),
                    system_prompt="test",
                    transcript_turns_min=4,
                    transcript_turns_max=4,
                    episode_unsummarized_tail_turns=2,
                    memory_results=2,
                    database=Path(directory) / "momoi.sqlite3",
                    log_level="INFO",
                )
            )
            event = IncomingMessage("reply:event", "1", "晚上选个游戏吧", 1, 1)
            daemon.store.add_event(event)
            owner_turn = daemon.store.commit_turn(
                [event],
                event.text,
                AgentReply(["那你想玩解谜还是动作呀"]),
            )
            outbox_id = daemon.store._db.execute(
                "SELECT id FROM outbox WHERE turn_id=?", (owner_turn,)
            ).fetchone()["id"]
            daemon.store.mark_sent(int(outbox_id))
            daemon.store._db.execute(
                """UPDATE self_state
                   SET pending_reply_turn_id=?,
                       pending_reply_expectation='主人对问题的回答',
                       pending_reply_since=1000,
                       pending_reply_last_reason='这个问题需要老师决定',
                       pending_reply_delay_minutes=4,
                       pending_reply_next_check_at=1240
                   WHERE id=1""",
                (owner_turn,),
            )
            daemon.store._db.commit()

            # Freeze the shared prefix before a dashboard edit during reply wait.
            from tests.test_transcript_memory import add
            memory_id = add(daemon.store, "等待期间的旧偏好")
            baseline = daemon.shared_turn_context("reply-followup")["messages"][0]["content"]
            daemon.store.update_memory_content(memory_id, "等待期间的新偏好")
            terminal = AgentReply([], reply_wait={"wait": False})
            with (
                patch.object(
                    daemon,
                    "_run_tool_loop",
                    new_callable=AsyncMock,
                    return_value=terminal,
                ) as run,
                patch.object(daemon.store, "commit_reply_followup"),
            ):
                await daemon._complete_reply_wait(
                    "reply-followup", "napcat", owner_event_revision=1
                )

            system = str(run.await_args.args[0])
            messages = run.await_args.args[1]
            tools = run.await_args.args[2]
            rendered = json.dumps(messages, ensure_ascii=False)
            self.assertEqual(messages[0]["content"], baseline)
            self.assertIn("等待期间的新偏好", rendered)
            self.assertIn("<replace", rendered)
            self.assertTrue(messages[2]["_memory_change"])
            draft = run.await_args.args[4]
            self.assertEqual(draft.memory_context[memory_id]["content"], "等待期间的新偏好")
            self.assertNotIn("Required reply follow-up", system)
            self.assertIn("<workflow_contract>", rendered)
            self.assertNotIn("<reply_timeline>", rendered)
            from xml.etree import ElementTree
            current = messages[-1]["content"][0]["text"]
            node = ElementTree.fromstring("<root>" + current + "</root>").find("followup")
            self.assertEqual(node.attrib["parent_turn_id"], owner_turn)
            self.assertGreaterEqual(int(node.attrib["silent_minutes"]), 0)
            self.assertEqual(node.find("reason").text, "这个问题需要老师决定")
            self.assertIsNone(node.find("followup"))
            self.assertIn("<recent_episodes>", str(messages[1]["content"]))
            self.assertEqual(
                [message["role"] for message in messages],
                ["user", "user", "user", "user"],
            )
            self.assertNotIn("[runtime time gap]", str(messages[-1]["content"]))
            self.assertNotIn("晚上选个游戏吧", rendered)
            self.assertNotIn("那你想玩解谜还是动作呀", rendered)
            self.assertEqual(
                tools,
                daemon.tool_surface.conversation_specs(),
            )
            daemon.store.close()


if __name__ == "__main__":
    unittest.main()
