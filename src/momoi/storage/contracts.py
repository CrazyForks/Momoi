"""Storage boundary records. JSON-compatible types preserve the public wire format.

TypedDict describes validated records, not untrusted model input. Runtime tool
validation remains responsible for rejecting malformed commands.
"""
from typing import Any, Literal, NotRequired, TypedDict


class PlanStepInput(TypedDict):
    task: str
    on_failure: Literal["stop", "continue"]


class PlanCreateInput(TypedDict):
    title: str
    request: str
    steps: list[PlanStepInput]


class PlanStep(PlanStepInput):
    id: str
    status: str
    turn_id: NotRequired[str]
    result: NotRequired[str]
    output_refs: NotRequired[list[str]]
    interrupted_turn_id: NotRequired[str]
    checkpoint_turn_id: NotRequired[str]
    pause_reason: NotRequired[str]
    paused_at: NotRequired[float]
    owner_feedback: NotRequired[dict[str, Any]]


class PlanRecord(TypedDict):
    id: str
    source_turn_id: str
    channel: str
    title: str
    request: str
    status: str
    steps: list[PlanStep]
    step_index: int
    created_at: float
    updated_at: float
    version: int
    context: dict[str, Any] | None
    review: dict[str, Any]


class ActiveMemory(TypedDict):
    id: int
    kind: str
    key: str
    content: str
    importance: float


class InventoryMemory(ActiveMemory):
    activation: str
    authority: str
    source_event_id: str | None
    evidence_quote: str | None
    created_at: float
    updated_at: float
    expires_at: float | None
    superseded_by: int | None


class PromptFingerprint(TypedDict):
    hash: str
    tokens_est: int


class RequestShape(TypedDict):
    settings_hash: str
    parts: list[PromptFingerprint]
    message_count: int
    input_tokens_est: int


class RequestMetricRecord(TypedDict):
    created_at: float
    request_id: str
    attempt: int
    model: str
    protocol: NotRequired[str]
    route: str
    shape: RequestShape
    status: Literal["success", "error", "cancelled"]
    usage: dict[str, float | int | bool] | None
    first_response_ms: float | None
    duration_ms: float
    http_status: NotRequired[int | None]
    error_type: NotRequired[str | None]
    turn_id: NotRequired[str]
    stage: NotRequired[str]
    call_id: NotRequired[str]
    round: NotRequired[int]


class MetricsPage(TypedDict):
    totals: dict[str, Any]
    stages: list[dict[str, Any]]
    trend: list[dict[str, Any]]
    items: list[dict[str, Any]]
    next_cursor: int | None
    filters: dict[str, list[str]]
    retention_days: int
    timing: str
