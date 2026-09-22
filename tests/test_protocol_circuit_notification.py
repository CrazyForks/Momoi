"""A stopped task gets a bounded delivery-only model phase, never another task attempt."""
import asyncio
from types import SimpleNamespace

import pytest

from momoi.models import ProviderResponse, ToolCall
from tests.test_memory_operations import daemon, event, response


@pytest.mark.parametrize("recovery", ["blocked_tool", "silent_end", "text_forever", "provider_error", "sent_then_error"])
def test_circuit_recovery_is_bounded_and_cannot_restart_task(daemon, recovery):
    source = event(daemon.store, text="帮我处理一下")
    turn_id = daemon._turn_id(source.event_id)
    limit = daemon.config.turn_max_protocol_retries
    rounds = 0
    notices = []

    async def complete(system, messages, tools, **kwargs):
        nonlocal rounds
        rounds += 1
        if rounds <= limit:
            return ProviderResponse([{"type": "text", "text": "没有调用工具"}], [])
        assert {t["name"] for t in tools} == {"send_bubbles", "end_turn"}
        assert "熔断" in str(system)
        assert "错误摘要" in str(messages)
        step = rounds - limit
        if recovery == "provider_error" or (recovery == "sent_then_error" and step > 1):
            raise RuntimeError("private upstream secret")
        if recovery == "text_forever":
            return ProviderResponse([{"type": "text", "text": "还是不用工具"}], [])
        if step == 1 and recovery == "blocked_tool":
            return response(ToolCall("forbidden", "write_file", {"path": "no", "content": "no"}))
        if step == 1 and recovery == "silent_end":
            return response(ToolCall("silent-end", "end_turn", {
                "mood": {"decision": "unchanged"}, "reply_wait": {"wait": False},
            }))
        if recovery == "sent_then_error" or step == 2:
            notices.append("任务没做完，工具连续出错，我先停下了。")
            return response(ToolCall("notice", "send_bubbles", {"bubbles": notices[-1:]}))
        return response(ToolCall("finish", "end_turn", {
            "mood": {"decision": "unchanged"}, "reply_wait": {"wait": False},
        }))

    daemon.provider = SimpleNamespace(complete=complete, config=SimpleNamespace(api_format="anthropic"))
    asyncio.run(daemon._complete_batch_turn([source], asyncio.Event(), turn_id))
    assert rounds <= limit + 3
    outbox = daemon.store.due_outbox()
    assert len(outbox) == 1
    assert "private upstream secret" not in outbox[0].text
    if notices:
        assert outbox[0].text == notices[0]
    else:
        assert outbox[0].text == "这次处理连续出错，已经停下了，没能完成。"
    assert not daemon.store._db.execute(
        "SELECT 1 FROM tool_audit WHERE turn_id=? AND tool_name='write_file'", (turn_id,)
    ).fetchone()
