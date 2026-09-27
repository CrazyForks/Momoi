import copy
from dataclasses import dataclass
from typing import Literal
from typing import Any

from ...models import AgentReply
from ..parsing import parse_response
from ..turn_support import ExternalToolTurnError, MAX_CONSECUTIVE_TOOL_FAILURES
from .workflow import TurnExecutionSpec, WorkflowProtocolError

_PRIVATE_REASONING_BLOCK_TYPES = frozenset(
    {"reasoning", "thinking", "redacted_thinking"}
)


def assistant_history_content(content: object) -> object:
    """Keep protocol output for the next round without replaying private thought."""

    if not isinstance(content, list):
        return copy.deepcopy(content)
    return [
        copy.deepcopy(block)
        for block in content
        if not (
            isinstance(block, dict)
            and block.get("type") in _PRIVATE_REASONING_BLOCK_TYPES
        )
    ]


def assistant_history_message(content: object, continuation: dict | None = None) -> dict:
    """Retain provider-owned continuation without turning it into visible text."""
    message = {"role": "assistant", "content": assistant_history_content(content)}
    if continuation:
        message["provider_continuation"] = copy.deepcopy(continuation)
    return message


@dataclass(frozen=True)
class NoToolResolution:
    action: Literal["retry", "return"]
    failed_rounds: int
    log_rejection: bool = False


def handle_no_tool_response(
    messages: list[dict[str, Any]],
    content: object,
    *,
    workflow_correction: str | None,
    heartbeat_turn: bool,
    harness_started: bool,
    goal_turn: bool,
    require_response: bool,
    owner_turn: bool,
    failed_rounds: int,
    last_tool_error: str,
    external_effect: bool = False,
    continuation: dict | None = None,
    max_failures: int = MAX_CONSECUTIVE_TOOL_FAILURES,
) -> NoToolResolution:
    if workflow_correction is not None or heartbeat_turn or goal_turn or require_response:
        failed_rounds += 1
        if failed_rounds >= max_failures:
            error_type = (
                ExternalToolTurnError
                if external_effect and workflow_correction is None
                else WorkflowProtocolError
            )
            raise error_type(
                last_tool_error or (
                    "repeated workflow protocol failures"
                    if workflow_correction is not None
                    else "native_tool_call_required"
                )
            )
    if workflow_correction is not None:
        messages.extend(
            [
                assistant_history_message(content, continuation),
                {"role": "user", "content": workflow_correction},
            ]
        )
        return NoToolResolution("retry", failed_rounds)
    if heartbeat_turn and not harness_started:
        messages.extend(
            [
                assistant_history_message(content, continuation),
                {
                    "role": "user",
                    "content": (
                        "[Trusted runtime protocol error: no native tool call was "
                        "returned. Call heartbeat_begin alone before any other "
                        "Heartbeat action.]"
                    ),
                },
            ]
        )
        return NoToolResolution("retry", failed_rounds)
    if goal_turn:
        messages.extend(
            [
                assistant_history_message(content, continuation),
                {
                    "role": "user",
                    "content": (
                        "[Trusted runtime protocol error. Plain text was not stored. "
                        "Use send_bubbles or send_voice to message the owner, continue with native tools, or call end_turn with the "
                        "empty arguments after goal_review succeeds.]"
                    ),
                },
            ]
        )
        return NoToolResolution("retry", failed_rounds)
    if not require_response:
        return NoToolResolution("return", failed_rounds)
    if owner_turn and not harness_started:
        correction = (
            "[Trusted runtime protocol error: no native tool call was returned. Call "
            "recall as a native tool in the opening batch; independent tools may "
            "accompany it. Never write or imitate tool syntax in text.]"
        )
    elif owner_turn:
        correction = (
            "[Trusted runtime protocol error: no native tool call was returned. "
            "Call send_bubbles or send_voice for owner-visible messages, "
            "then end_turn when ready; both may occur in the same response.]"
        )
    else:
        correction = (
            "[Trusted runtime protocol error: no native tool call was returned. "
            "Continue with native tool calls following the current workflow.]"
        )
    messages.extend(
        [
            assistant_history_message(content, continuation),
            {"role": "user", "content": correction},
        ]
    )
    return NoToolResolution("retry", failed_rounds, log_rejection=True)


def owner_request_messages(
    messages: list[dict[str, Any]], *, remind_bubbles: bool
) -> list[dict[str, Any]]:
    """Build an Owner-only wire copy without changing canonical Turn history."""

    return copy.deepcopy(messages)


def parse_end_turn(
    arguments: dict[str, Any],
    *,
    execution: TurnExecutionSpec,
    visible_since_owner_update: bool,
) -> tuple[AgentReply | None, str | None]:
    if not execution.require_response:
        return None, "end_turn_not_allowed"
    reply, error = parse_response(arguments)
    if reply is None:
        return None, error
    if reply.expects_reply and not visible_since_owner_update:
        return None, "reply_expectation_without_visible_bubble"
    if execution.reply_followup:
        if reply.should_schedule_reply_wait:
            return None, "reply_followup_cannot_schedule_another_wait"
    return reply, None
