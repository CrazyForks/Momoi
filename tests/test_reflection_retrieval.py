import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

from momoi.models import ToolCall
from momoi.storage import Store
from momoi.runtime.workflows.reflection_retrieval import ReflectionRetrieval


class ReflectionRetrievalTest(unittest.IsolatedAsyncioTestCase):
    async def test_raw_search_preserves_provenance_and_excludes_future(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory) / "test.sqlite3")
            self.addCleanup(store.close)
            for role, content, stamp, delivery in (
                ("user", "过去说过苹果", 10, "delivered"),
                ("assistant", "苹果未发送", 20, "uncertain"),
                ("user", "未来说苹果", 40, "delivered"),
            ):
                store._db.execute(
                    "INSERT INTO messages(role, content, created_at, delivery_state, source_event_ids_json) VALUES (?, ?, ?, ?, '[]')",
                    (role, content, stamp, delivery),
                )
            tools = AsyncMock()
            retrieval = ReflectionRetrieval(store, tools, 30)
            first = await retrieval.execute(ToolCall("1", "conversation_search", {"query": "苹果", "limit": 1}))
            self.assertEqual(first["messages"][0]["delivery_state"], "uncertain")
            self.assertEqual(first["next_cursor"], 1)
            second = await retrieval.execute(ToolCall("2", "conversation_search", {"query": "苹果", "limit": 1, "cursor": 1}))
            self.assertEqual(second["messages"][0]["content"], "过去说过苹果")
            self.assertIsNone(second["next_cursor"])
            invalid = await retrieval.execute(ToolCall("3", "conversation_search", {"query": "苹果", "limit": 100}))
            self.assertFalse(invalid["ok"])
            denied = await retrieval.execute(ToolCall("4", "memory_operation", {}))
            self.assertEqual(denied["error"], "tool_not_allowed")
            tools.execute_async.assert_not_awaited()

    async def test_recall_uses_read_only_memory_and_episode_search(self):
        tools = AsyncMock()
        tools.execute_async.return_value = {"ok": True}
        retrieval = ReflectionRetrieval(None, tools, 30)
        result = await retrieval.execute(ToolCall("1", "recall", {"query": "旧约定"}))
        self.assertTrue(result["ok"])
        self.assertEqual([call.args[0].name for call in tools.execute_async.await_args_list], ["memory_search", "episode_search"])
        self.assertEqual(retrieval.draft.memory_operations, [])
