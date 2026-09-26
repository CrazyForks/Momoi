"""Stable, compact observations for completed-turn replay only."""

import json
from collections.abc import Mapping


EDGE_CHARS = 80
SMALL_RESULT_CHARS = 600


def preview(text: str) -> str:
    if len(text) <= EDGE_CHARS * 2:
        return text
    return text[:EDGE_CHARS] + "\n[...truncated...]\n" + text[-EDGE_CHARS:]


def historical_results(exchanges: list[dict]) -> None:
    """Edit a private replay copy; never alter the journal or live observations.

    Error runs are summarized in the first result, with paired references in
    subsequent results. Different errors remain distinguishable in the summary.
    """
    run: list[tuple[dict, dict]] = []
    run_name = ""

    def flush() -> None:
        if len(run) < 2:
            run.clear()
            return
        first_id = run[0][0].get("tool_use_id")
        errors: dict[str, int] = {}
        for _, payload in run:
            detail = preview(str(payload.get("error") or "tool_failed") + ": "
                             + str(payload.get("message") or ""))
            errors[detail] = errors.get(detail, 0) + 1
        for index, (block, payload) in enumerate(run):
            compact = {"ok": False, "result_ref": payload.get("result_ref")}
            if index == 0:
                compact.update(error_run_count=len(run), errors=[
                    {"detail": detail, "count": count} for detail, count in errors.items()
                ])
            else:
                compact["error_summary_tool_use_id"] = first_id
            block["content"] = json.dumps(compact, ensure_ascii=False)
        run.clear()

    for exchange in exchanges:
        content = exchange.get("content")
        calls = {b.get("id"): b.get("name") for b in content
                 if isinstance(b, dict) and b.get("type") == "tool_use"} if isinstance(content, list) else {}
        if not calls:
            flush()
        for block in exchange.get("results", []):
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                flush()
                continue
            raw = block.get("content")
            if not isinstance(raw, str):
                flush()
                continue
            try:
                payload = json.loads(raw)
            except (ValueError, TypeError):
                payload = {}
            if not isinstance(payload, Mapping):
                payload = {}
            name = calls.get(block.get("tool_use_id"), "")
            # Recall evidence is the basis for subsequent reuse. Preserve the
            # exact observation, including failures, regardless of its size.
            if name == "recall":
                flush()
                run_name = ""
                continue
            if name and payload.get("ok") is False:
                if run_name != name:
                    flush()
                run_name = name
                run.append((block, dict(payload)))
            else:
                flush()
                run_name = ""
            if len(raw) <= SMALL_RESULT_CHARS:
                continue
            compact = {key: payload[key] for key in (
                "ok", "error", "provenance", "result_ref", "original_chars",
                "chunk_start", "chunk_end", "next_cursor", "has_more",
            ) if key in payload}
            body = payload.get("content", raw)
            if not isinstance(body, str):
                body = json.dumps(body, ensure_ascii=False)
            compact.update(history_truncated=True, preview=preview(body))
            block["content"] = json.dumps(compact, ensure_ascii=False)
    flush()
