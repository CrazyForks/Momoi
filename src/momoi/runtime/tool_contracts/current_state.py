"""Stable visible schema; the harness grants execution only during maintenance."""

from ...storage.memory.current_state import CurrentStateManager


def current_state_finish_spec() -> dict:
    return {
        "name": "current_state_finish",
        "description": (
            '提交当前状态变更集，并在对话回合提交后完成私有维护阶段。仅在 current_state_maintenance 期间可调用；对话本身期间不可用。这是维护阶段中唯一的写状态工具；memory_operation 用于此处的持久化记忆。请使用当前快照，而非旧的工具结果；请勿重复已完成的变更或更新其 TTL。'
        ),
        "input_schema": CurrentStateManager.change_schema(),
    }
