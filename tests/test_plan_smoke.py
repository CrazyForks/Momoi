"""Plan transcript contract and step workflow integration tests.

Provider responses are scripted; execution and delivery use the real runtime.
The step() fixture isolates transcript edge cases; production tests exercise
persistent claims and the production step workflow.
"""

import copy
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

from momoi.channel.napcat import NapCatConfig
from momoi.config.models import AppConfig
from momoi.integrations.models import LLMConfig
from momoi.models import AgentReply, IncomingMessage, ProviderResponse, ToolCall
from momoi.runtime import MomoiDaemon
from momoi.runtime.agent import AgentWorkflow, WorkflowProtocolError
from momoi.runtime.workflows.plan_context import plan_step_messages
from tests.support import provider_catalog


FINISH = {
    "name": "plan_step_finish", "description": "Report the current step outcome.",
    "input_schema": {
        "type": "object", "properties": {
            "outcome": {"enum": ["succeeded", "failed"]},
            "summary": {"type": "string", "minLength": 1},
        }, "required": ["outcome", "summary"], "additionalProperties": False,
    },
}


class PlanSmokeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.daemon = MomoiDaemon(AppConfig(
            providers=provider_catalog(LLMConfig("http://localhost", "test", "model", 100, 0, 1, 0)),
            channel=NapCatConfig("ws://localhost", "123", 1, 60, 30, 30, 20),
            transcript_turns_min=4, transcript_turns_max=4, episode_unsummarized_tail_turns=2,
            memory_results=2, log_level="INFO",
            system_prompt="Momoi role and voice", database=Path(directory.name) / "store.sqlite3",
        ))
        self.addCleanup(self.daemon.store.close)
        event = IncomingMessage("plan-request", "1", "看 A B C 的微博并发给我", 1, 1)
        self.daemon.store.add_event(event)
        self.owner_turn = self.daemon.store.commit_turn([event], event.text, AgentReply(["我来看看。 "]))
        self.turns = [self.owner_turn]
        self.records = []
        self.requests = []

    async def step(self, index, script):
        daemon = self.daemon
        turn_id = f"plan-smoke:{index}"
        daemon.store.begin_turn(turn_id, "plan_step", ["plan:smoke"])
        rows = daemon.store.conversation_messages_for_turns(self.turns) + self.records
        messages = plan_step_messages(
            rows, timezone=daemon.store.timezone,
            current_step=f"Original request: 看 A B C 的微博并发给我; step {index}",
            tool_activity=daemon.store.turn_activity(self.turns),
        )
        self.requests.append(copy.deepcopy(messages))
        remaining = iter(script)

        async def complete(*args, **kwargs):
            call = next(remaining)
            return ProviderResponse([{
                "type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments,
            }], [call])

        daemon.provider = SimpleNamespace(complete=complete)
        outcome = None

        async def finish(call):
            nonlocal outcome
            args = call.arguments
            if (set(args) != {"outcome", "summary"}
                    or args["outcome"] not in {"succeeded", "failed"}
                    or not isinstance(args["summary"], str) or not args["summary"].strip()):
                return {"ok": False, "error": "invalid_plan_step_outcome"}
            outcome = dict(args)
            return {"ok": True}

        result = await daemon._run_agent_workflow(
            daemon._system(), messages, [daemon.tool_surface.send_bubbles_spec(), FINISH],
            turn_id, AgentWorkflow(
                stage="plan_step", tool_names=frozenset({"plan_step_finish"}),
                execute_tool=finish, is_complete=lambda: outcome is not None,
                completion_result=lambda: outcome,
                no_tool_correction="Finish the current step with plan_step_finish.",
            ),
        )
        # Persistence adapter is deliberately test-only until Plan storage lands.
        with daemon.store._db:
            daemon.store._archive_progress_messages(turn_id, '["plan:smoke"]')
            daemon.store.complete_background_turn(turn_id)
        self.turns.append(turn_id)
        self.records.append({
            "id": 10000 + index, "turn_id": turn_id, "role": "plan_step",
            "content": f"Plan smoke; step {index}; {result['outcome']}: {result['summary']}",
            "created_at": time.time(), "delivery_state": "internal",
        })
        return result

    @staticmethod
    def finish(outcome="succeeded", summary="checked"):
        return ToolCall("finish", "plan_step_finish", {"outcome": outcome, "summary": summary})

    async def test_three_sends_advance_without_owner_continuation(self):
        await self.step(0, [self.finish(summary="access method confirmed")])
        for index, user in enumerate("ABC", 1):
            await self.step(index, [
                ToolCall("send", "send_bubbles", {"bubbles": [f"{user} latest post"]}),
                self.finish(summary=f"{user} queued"),
            ])
        pending = [row[0] for row in self.daemon.store._db.execute("SELECT text FROM outbox ORDER BY id")]
        self.assertEqual(pending[-3:], [f"{user} latest post" for user in "ABC"])
        last = self.requests[-1]
        text = str(last)
        self.assertEqual(text.count("A latest post"), 1)
        self.assertIn('delivery="queued"', text)
        self.assertIn('<plan_step id="P10000"', text)
        self.assertIn("access method confirmed", text)
        self.assertNotIn("owner did not reply", text)
        self.assertNotIn("previous assistant messages still being delivered", text)
        self.assertNotIn("ended the Turn without replying", text)
        self.assertNotIn("tool_use", text)
        self.assertIn("<current_plan_step>", str(last[-1]))
        self.assertNotIn("<current_plan_step>", str(last[:-1]))
        self.assertTrue(any(m["role"] == "assistant" and "A latest post" in str(m) for m in last))

    async def test_access_failure_stops_before_user_steps(self):
        for index in range(4):
            result = await self.step(index, [
                ToolCall("notice", "send_bubbles", {"bubbles": ["无法访问微博，任务已停止。"]}),
                self.finish("failed", "access unavailable"),
            ])
            if result["outcome"] == "failed":
                break
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(len(self.daemon.store.due_outbox()), 2)

    async def test_invalid_finish_uses_existing_circuit_breaker(self):
        with self.assertRaises(WorkflowProtocolError):
            await self.step(0, [
                ToolCall(str(i), "plan_step_finish", {})
                for i in range(self.daemon.config.turn_max_protocol_retries)
            ])
        self.assertEqual(self.records, [])

    def test_window_starting_with_assistant_keeps_native_speech(self):
        rows = [{"id": 1, "turn_id": "old", "role": "assistant", "content": "已写的原文",
                 "created_at": 1, "delivery_state": "uncertain"}]
        messages = plan_step_messages(rows, timezone=self.daemon.store.timezone, current_step="续写 <下一章>")
        self.assertEqual([m["role"] for m in messages], ["user", "assistant", "user"])
        self.assertIn("delivery uncertain", str(messages[1]))
        self.assertIn("&lt;下一章&gt;", str(messages[-1]))

    async def test_owner_message_pauses_running_plan_step(self):
        import asyncio

        daemon = self.daemon
        plan = daemon.store.create_task_plan(
            {"title": "old request", "request": "send old result", "steps": [
                {"task": "send old result", "on_failure": "stop"},
            ]}, self.owner_turn, daemon.channel.name,
        )
        daemon.store.start_task_plan(plan["id"], daemon.channel.name, {
            "system": daemon._system(),
            "tools": daemon.tool_surface.conversation_specs(),
            "messages": [],
        })
        daemon.store.claim_task_plan()
        started = asyncio.Event()

        async def complete(*args, **kwargs):
            started.set()
            await asyncio.sleep(3600)

        daemon.provider = SimpleNamespace(complete=complete)
        daemon._active_turn_stage = "plan_step"
        daemon._active_turn_channel = daemon.channel.name
        daemon._active_turn = asyncio.create_task(
            daemon._complete_plan_step_turn(plan["id"], asyncio.Event())
        )
        await asyncio.wait_for(started.wait(), 1)
        update = IncomingMessage("plan-update", "plan-update", "改一下要求", time.time(), time.time())
        await daemon._receive(update)
        with self.assertRaises(asyncio.CancelledError):
            await daemon._active_turn
        self.assertEqual(daemon.store.task_plan(plan["id"])["status"], "paused")
        self.assertEqual(daemon.store.pending_events()[-1].text, update.text)
        self.assertEqual(daemon._interrupt_reason, "owner_update")
        self.assertIn("paused", daemon._interruption_notices[daemon.channel.name][0])

    def test_paused_plan_can_resume_or_update_remaining_steps(self):
        store = self.daemon.store
        plan = store.create_task_plan({
            "title": "three steps", "request": "send A B C", "steps": [
                {"task": f"send {item}", "on_failure": "stop"} for item in "ABC"
            ],
        }, self.owner_turn, self.daemon.channel.name)
        store.start_task_plan(plan["id"], self.daemon.channel.name, {
            "system": [], "tools": [], "messages": [],
        })
        store.claim_task_plan()
        interrupted = "plan-interrupted-safe"
        store.begin_turn(interrupted, "plan_step", [f"plan:{plan['id']}"])
        store.cancel_turn(interrupted, reason="owner_update")
        paused = store.pause_task_plan(plan["id"], interrupted)
        self.assertEqual(paused["status"], "paused")
        self.assertEqual(store.plan_resume_safety(paused), "safe")
        revised = store.update_task_plan(plan["id"], self.daemon.channel.name,
                                         paused["version"], [
            {"task": "send revised A", "on_failure": "stop"},
            {"task": "send B", "on_failure": "stop"},
        ], "send revised A and B")
        self.assertEqual(revised["request"], "send revised A and B")
        self.assertEqual(revised["steps"][0]["interrupted_turn_id"], interrupted)
        resumed = store.resume_task_plan(plan["id"], self.daemon.channel.name,
                                         revised["version"], {
            "system": [], "tools": [], "messages": [{"role": "user", "content": "BTW and correction"}],
        })
        self.assertEqual(resumed["status"], "ready")
        self.assertEqual(resumed["steps"][0]["task"], "send revised A")
        self.assertEqual(resumed["context"]["completed_through"], 0)
        self.assertEqual(store.claim_task_plan()["id"], plan["id"])

    def test_paused_plan_with_visible_progress_cannot_replay(self):
        store = self.daemon.store
        plan = store.create_task_plan({
            "title": "sent something", "request": "send A", "steps": [
                {"task": "send A", "on_failure": "stop"},
            ],
        }, self.owner_turn, self.daemon.channel.name)
        store.start_task_plan(plan["id"], self.daemon.channel.name, {
            "system": [], "tools": [], "messages": [],
        })
        store.claim_task_plan()
        interrupted = "plan-interrupted-visible"
        store.begin_turn(interrupted, "plan_step", [f"plan:{plan['id']}"])
        store.queue_progress(interrupted, "sent-A", ["A"], self.daemon.channel.name)
        store.cancel_turn(interrupted, reason="owner_update")
        paused = store.pause_task_plan(plan["id"], interrupted)
        self.assertEqual(store.plan_resume_safety(paused), "requires_review")
        with self.assertRaisesRegex(ValueError, "may have acted externally"):
            store.resume_task_plan(plan["id"], self.daemon.channel.name,
                                   paused["version"], {"system": [], "tools": [], "messages": []})

    async def test_stop_cancels_active_webhook_turn(self):
        import asyncio

        daemon = self.daemon
        started = asyncio.Event()
        turn_id = "webhook:test-stop:0"

        async def complete_webhook(prompt, active_turn_id, channel):
            daemon.store.begin_turn(active_turn_id, "webhook", [active_turn_id])
            started.set()
            await asyncio.sleep(3600)

        daemon._complete_webhook_turn = complete_webhook
        stop = asyncio.Event()
        worker = asyncio.create_task(daemon._agent_worker(stop))
        request = asyncio.create_task(daemon._request_webhook_turn("old event", turn_id))
        try:
            await asyncio.wait_for(started.wait(), 1)
            await daemon._receive(
                IncomingMessage("stop-webhook", "stop-webhook", "/stop", time.time(), time.time())
            )
            with self.assertRaisesRegex(RuntimeError, "owner_stop"):
                await asyncio.wait_for(request, 1)
            state = daemon.store._db.execute(
                "SELECT state FROM turns WHERE id=?", (turn_id,)
            ).fetchone()[0]
            self.assertEqual(state, "cancelled")
            self.assertFalse(daemon._webhook_turn_active)
        finally:
            worker.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await worker

    async def test_production_step_failure_stops_and_restart_does_not_replay(self):
        import asyncio
        daemon = self.daemon
        plan = daemon.store.create_task_plan({"title": "failure", "request": "test", "steps": [
            {"task": "access", "on_failure": "stop"}, {"task": "never", "on_failure": "stop"},
        ]}, self.owner_turn, daemon.channel.name)
        daemon.store.start_task_plan(plan["id"], daemon.channel.name, {"system": daemon._system(), "tools": daemon.tool_surface.conversation_specs(), "messages": []})
        daemon.store.claim_task_plan()

        async def complete(*args, **kwargs):
            call = ToolCall("finish", "plan_step_finish", {
                "outcome": "failed", "summary": "cannot access", "output_refs": [], "abort_remaining": True,
            })
            return ProviderResponse([{"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}], [call])

        daemon.provider = SimpleNamespace(complete=complete)
        await daemon._complete_plan_step_turn(plan["id"], asyncio.Event())
        self.assertEqual(daemon.store.task_plan(plan["id"])["status"], "failed")
        self.assertIsNone(daemon.store.claim_task_plan())
        with self.assertRaises(ValueError):
            daemon.store.start_task_plan(plan["id"], daemon.channel.name, {"system": daemon._system(), "tools": daemon.tool_surface.conversation_specs(), "messages": []})
        other = daemon.store.create_task_plan({"title": "restart", "request": "test", "steps": [{"task": "x", "on_failure": "stop"}]}, self.owner_turn, daemon.channel.name)
        daemon.store.start_task_plan(other["id"], daemon.channel.name)
        daemon.store.claim_task_plan()
        daemon.store.recover_task_plans()
        self.assertEqual(daemon.store.task_plan(other["id"])["status"], "blocked")
        self.assertIsNone(daemon.store.claim_task_plan())

    async def test_production_successful_tools_cannot_loop_forever(self):
        import asyncio
        daemon = self.daemon
        plan = daemon.store.create_task_plan({"title": "bounded", "request": "test", "steps": [{"task": "read", "on_failure": "stop"}]}, self.owner_turn, daemon.channel.name)
        daemon.store.start_task_plan(plan["id"], daemon.channel.name, {"system": daemon._system(), "tools": daemon.tool_surface.conversation_specs(), "messages": []})
        daemon.store.claim_task_plan()
        ref = daemon.tool_results.save('{"ok":true,"content":"unchanged"}')
        calls = 0

        async def complete(*args, **kwargs):
            nonlocal calls
            calls += 1
            self.assertLessEqual(calls, 24)
            call = ToolCall(str(calls), "read_tool_result", {"result_ref": ref})
            return ProviderResponse([{"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}], [call])

        daemon.provider = SimpleNamespace(complete=complete)
        await daemon._complete_plan_step_turn(plan["id"], asyncio.Event())
        self.assertEqual(calls, 24)
        self.assertEqual(daemon.store.task_plan(plan["id"])["status"], "blocked")
        self.assertIsNone(daemon.store.claim_task_plan())

    async def test_stop_cancels_queued_plan_and_scheduler_claim_is_unique(self):
        daemon = self.daemon
        plan = daemon.store.create_task_plan({"title": "cancel", "request": "test", "steps": [{"task": "send", "on_failure": "stop"}]}, self.owner_turn, daemon.channel.name)
        daemon.store.start_task_plan(plan["id"], daemon.channel.name, {"system": daemon._system(), "tools": daemon.tool_surface.conversation_specs(), "messages": []})
        daemon.store.start_task_plan(plan["id"], daemon.channel.name, {"system": daemon._system(), "tools": daemon.tool_surface.conversation_specs(), "messages": []})
        self.assertEqual(daemon.store.claim_task_plan()["id"], plan["id"])
        self.assertIsNone(daemon.store.claim_task_plan())
        await daemon._receive(IncomingMessage("plan-stop", "1", "/stop", time.time(), 1))
        self.assertEqual(daemon.store.task_plan(plan["id"])["status"], "cancelled")
        self.assertIsNone(daemon.store.claim_task_plan())

    def test_plan_tools_have_no_exclusive_batch_requirement(self):
        from momoi.runtime.agent import TurnHarness
        harness = TurnHarness.for_stage("owner")
        self.assertIsNone(harness.validate([
            ToolCall("recall", "recall", {}), ToolCall("create", "plan_create", {}),
            ToolCall("start", "plan_start", {}),
        ]))
        step = TurnHarness.for_stage("plan_step")
        self.assertIsNone(step.validate([
            ToolCall("send", "send_bubbles", {}), ToolCall("finish", "plan_step_finish", {}),
        ]))

    async def test_shared_schema_does_not_grant_step_owner_permissions(self):
        import asyncio
        import json
        daemon = self.daemon
        tools = daemon.tool_surface.conversation_specs()
        plan = daemon.store.create_task_plan({
            "title": "permissions", "request": "test",
            "steps": [{"task": "finish", "on_failure": "stop"}],
        }, self.owner_turn, daemon.channel.name)
        daemon.store.start_task_plan(plan["id"], daemon.channel.name, {
            "system": daemon._system(), "tools": tools, "messages": [],
        })
        daemon.store.claim_task_plan()
        calls = 0

        async def complete(system, messages, request_tools, **kwargs):
            nonlocal calls
            calls += 1
            self.assertEqual(request_tools, tools)
            if calls == 1:
                call = ToolCall("forbidden", "plan_create", {
                    "title": "must not exist", "request": "nested",
                    "steps": [{"task": "nested", "on_failure": "stop"}],
                })
            else:
                self.assertEqual(calls, 2)
                result = json.loads(messages[-1]["content"][0]["content"])
                self.assertFalse(result["ok"])
                self.assertEqual(result["error"], "tool_not_allowed")
                call = ToolCall("finish", "plan_step_finish", {
                    "outcome": "succeeded", "summary": "done",
                    "output_refs": [], "abort_remaining": False,
                })
            return ProviderResponse([{
                "type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments,
            }], [call])

        daemon.provider = SimpleNamespace(complete=complete)
        await daemon._complete_plan_step_turn(plan["id"], asyncio.Event())
        self.assertEqual(calls, 2)
        self.assertEqual(daemon.store.task_plan(plan["id"])["status"], "completed")
        self.assertEqual(daemon.store._db.execute("SELECT COUNT(*) FROM task_plans").fetchone()[0], 1)
        self.assertNotIn("plan_step_finish", daemon.tool_surface.permitted_names("owner"))


    async def test_plan_step_can_search_memory(self):
        import asyncio
        import json
        daemon = self.daemon
        plan = daemon.store.create_task_plan({
            "title": "memory search", "request": "look up memory",
            "steps": [{"task": "search memory", "on_failure": "stop"}],
        }, self.owner_turn, daemon.channel.name)
        daemon.store.start_task_plan(plan["id"], daemon.channel.name, {
            "system": daemon._system(), "tools": daemon.tool_surface.conversation_specs(),
            "messages": [],
        })
        daemon.store.claim_task_plan()
        calls = 0

        async def complete(system, messages, tools, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                call = ToolCall("search", "memory_search", {"query": "游戏"})
            else:
                self.assertEqual(calls, 2)
                result = json.loads(messages[-1]["content"][0]["content"])
                self.assertTrue(result["ok"], result)
                call = ToolCall("finish", "plan_step_finish", {
                    "outcome": "succeeded", "summary": "searched",
                    "output_refs": [], "abort_remaining": False,
                })
            return ProviderResponse([{
                "type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments,
            }], [call])

        daemon.provider = SimpleNamespace(complete=complete)
        await daemon._complete_plan_step_turn(plan["id"], asyncio.Event())
        self.assertEqual(calls, 2)
        self.assertEqual(daemon.store.task_plan(plan["id"])["status"], "completed")
