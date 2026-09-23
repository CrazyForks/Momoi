import unittest

from momoi.models import ToolCall
from momoi.runtime.agent import TURN_HARNESS_SPECS, TurnHarness
from momoi.runtime.agent.protocol import (
    assistant_history_content,
    handle_no_tool_response,
)
from momoi.runtime.turn_support import ExternalToolTurnError, MAX_CONSECUTIVE_TOOL_FAILURES
from momoi.runtime.agent.workflow import WorkflowProtocolError


class TurnHarnessTest(unittest.TestCase):
    def test_no_tool_failures_stop_at_the_shared_limit(self) -> None:
        for stage in TURN_HARNESS_SPECS:
            for started in (False, True):
                for external_effect in (False, True):
                    with self.subTest(stage=stage, started=started, external_effect=external_effect):
                        workflow = stage in {
                            "plan_step", "reflection", "memory_maintenance", "memory_operation",
                            "episode_consolidate", "episode_anneal",
                            "current_state_maintenance",
                        }
                        messages = []
                        failed_rounds = 0
                        error_type = (
                            ExternalToolTurnError
                            if external_effect and not workflow
                            else WorkflowProtocolError
                        )
                        for attempt in range(1, MAX_CONSECUTIVE_TOOL_FAILURES + 1):
                            arguments = dict(
                                workflow_correction="Use native tools" if workflow else None,
                                heartbeat_turn=stage == "heartbeat",
                                harness_started=started,
                                goal_turn=stage == "goal",
                                require_response=stage in {
                                    "owner", "heartbeat", "webhook", "reply_followup",
                                },
                                owner_turn=stage == "owner",
                                failed_rounds=failed_rounds,
                                last_tool_error="",
                                external_effect=external_effect,
                            )
                            if attempt == MAX_CONSECUTIVE_TOOL_FAILURES:
                                with self.assertRaises(error_type):
                                    handle_no_tool_response(messages, "hello", **arguments)
                            else:
                                resolution = handle_no_tool_response(
                                    messages, "hello", **arguments,
                                )
                                failed_rounds = resolution.failed_rounds
                                self.assertEqual(failed_rounds, attempt)

    def test_owner_text_corrections_preserve_response_and_request_retry(self) -> None:
        for started in (False, True):
            with self.subTest(started=started):
                messages = []
                resolution = handle_no_tool_response(
                    messages, "hello", workflow_correction=None, heartbeat_turn=False,
                    harness_started=started, goal_turn=False, require_response=True,
                    owner_turn=True, failed_rounds=0, last_tool_error="",
                )
                self.assertEqual(resolution.action, "retry")
                self.assertEqual(messages[0], {"role": "assistant", "content": "hello"})
                self.assertEqual(messages[-1]["role"], "user")

    def test_private_reasoning_is_not_replayed_between_rounds(self) -> None:
        content = [
            {"type": "reasoning", "text": "openai private thought"},
            {"type": "thinking", "thinking": "anthropic private thought"},
            {"type": "redacted_thinking", "data": "opaque"},
            {"type": "tool_use", "id": "1", "name": "curl", "input": {}},
        ]

        self.assertEqual(
            assistant_history_content(content),
            [{"type": "tool_use", "id": "1", "name": "curl", "input": {}}],
        )

    def test_every_model_turn_stage_has_an_explicit_harness(self) -> None:
        self.assertEqual(
            set(TURN_HARNESS_SPECS),
            {
                "owner",
                "heartbeat",
                "reply_followup",
                "webhook",
                "goal",
                "reflection",
                "memory_maintenance", "memory_operation",
                "episode_consolidate",
                "episode_anneal",
                "current_state_maintenance", "plan_step",
            },
        )

    def test_empty_first_states_are_declared_not_implicit(self) -> None:
        for stage in {
            "webhook",
            "goal",
            "reflection",
            "memory_maintenance", "memory_operation",
            "episode_consolidate",
            "episode_anneal",
            "current_state_maintenance",
        }:
            with self.subTest(stage=stage):
                harness = TurnHarness.for_stage(stage)
                self.assertIsNone(harness.spec.first_tool)
                self.assertTrue(harness.started)

    def test_owner_opening_batch_requires_exactly_one_recall_in_any_position(self) -> None:
        harness = TurnHarness.for_stage("owner")
        recall = ToolCall("recall", "recall", {})
        send = ToolCall("send", "send_bubbles", {"bubbles": ["ok"]})

        for calls in ([recall], [recall, send], [send, recall]):
            self.assertIsNone(harness.validate(calls, required_tool="recall"))
        for calls in ([], [send], [recall, recall], [send, recall, recall]):
            self.assertEqual(
                harness.validate(calls), "recall_required_once_in_opening_batch",
            )
        end = ToolCall("end", "end_turn", {})
        self.assertEqual(harness.validate([recall, end]), "end_turn_must_be_alone")
        harness.accept("recall")
        self.assertIsNone(harness.validate([recall]))
        self.assertIsNone(harness.validate([send]))
        harness.accept_owner_update()
        self.assertIsNone(harness.validate([send, recall]))

    def test_webhook_harness_rejects_tools_outside_its_contract(self) -> None:
        harness = TurnHarness.for_stage("webhook")

        self.assertEqual(
            harness.validate([ToolCall("memory", "memory_search", {"query": "x"})]),
            "tool_not_allowed",
        )
        self.assertIsNone(
            harness.validate([ToolCall("curl", "curl", {"url": "https://x"})])
        )

    def test_current_state_harness_allows_optional_recall(self) -> None:
        harness = TurnHarness.for_stage("current_state_maintenance")
        self.assertIsNone(harness.validate([ToolCall("recall", "recall", {})]))
        self.assertIsNone(harness.validate([ToolCall("finish", "current_state_finish", {})]))
        self.assertEqual(
            harness.validate([ToolCall("send", "send_bubbles", {})]),
            "tool_not_allowed",
        )

    def test_required_tool_is_enforced_without_surface_projection(self) -> None:
        harness = TurnHarness.for_stage("goal")

        self.assertEqual(
            harness.validate(
                [ToolCall("work", "goal_update", {})],
                required_tool="end_turn",
            ),
            "end_turn_required",
        )
        harness.accept("goal_review")
        self.assertIsNone(
            harness.validate(
                [ToolCall("finish", "end_turn", {})],
                required_tool="end_turn",
            )
        )

    def test_harness_requires_its_boundary_tools_on_the_surface(self) -> None:
        harness = TurnHarness.for_stage("owner")

        with self.assertRaisesRegex(ValueError, "end_turn, recall"):
            harness.validate_surface(set())
        harness.validate_surface({"recall", "send_bubbles", "end_turn"})

    def test_only_heartbeat_has_an_explicit_opening_in_autonomous_chat(self) -> None:
        self.assertEqual(
            TurnHarness.for_stage("heartbeat").spec.first_tool,
            "heartbeat_begin",
        )
        self.assertEqual(
            TurnHarness.for_stage("reply_followup").spec.first_tool,
            None,
        )

    def test_heartbeat_requires_separate_successful_recall_for_each_send(self) -> None:
        harness = TurnHarness.for_stage("heartbeat")
        begin = ToolCall("begin", "heartbeat_begin", {})
        recall = ToolCall("recall", "recall", {})
        send = ToolCall("send", "send_bubbles", {})
        voice = ToolCall("voice", "send_voice", {})

        self.assertIsNone(harness.validate([begin]))
        harness.accept("heartbeat_begin")
        self.assertEqual(harness.validate([send]), "heartbeat_recall_required_before_send")
        self.assertEqual(harness.validate([recall, send]), "heartbeat_recall_required_before_send")
        harness.accept("recall")
        self.assertEqual(harness.validate([recall, send]), "heartbeat_recall_required_before_send")
        self.assertEqual(harness.validate([send, voice]), "heartbeat_one_send_per_recall")
        self.assertIsNone(harness.validate([send]))
        harness.accept("send_bubbles")
        self.assertEqual(harness.validate([voice]), "heartbeat_recall_required_before_send")
        harness.accept("recall")
        self.assertIsNone(harness.validate([voice]))

    def test_reply_followup_can_work_before_or_after_optional_delivery(self) -> None:
        harness = TurnHarness.for_stage("reply_followup")
        work = ToolCall("work", "read_file", {"path": "notes.txt"})
        send = ToolCall("send", "send_bubbles", {"bubbles": ["我再看看"]})
        end = ToolCall("end", "end_turn", {})

        self.assertIsNone(harness.validate([work]))
        self.assertIsNone(harness.validate([send]))
        harness.accept("send_bubbles")
        self.assertIsNone(harness.validate([work]))
        self.assertIsNone(harness.validate([end]))

    def test_terminal_tool_must_be_alone_for_every_stage(self) -> None:
        work = ToolCall("work", "work", {})
        for stage, spec in TURN_HARNESS_SPECS.items():
            with self.subTest(stage=stage):
                harness = TurnHarness.for_stage(stage)
                if spec.first_tool is not None:
                    harness.accept(spec.first_tool)
                terminal = ToolCall("terminal", spec.terminal_tool, {})
                self.assertEqual(
                    harness.validate([work, terminal]),
                    f"{spec.terminal_tool}_must_be_alone" if spec.terminal_alone else None,
                )

    def test_unknown_stage_cannot_fall_back_to_an_empty_harness(self) -> None:
        with self.assertRaisesRegex(ValueError, "missing Turn harness"):
            TurnHarness.for_stage("unknown")


if __name__ == "__main__":
    unittest.main()
