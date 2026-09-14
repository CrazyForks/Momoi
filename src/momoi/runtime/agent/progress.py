import copy
from typing import Any

from ...contracts import OWNER_PROGRESS_FIELD


def public_tool_spec(spec: dict[str, Any]) -> dict[str, Any]:
    public = copy.deepcopy(spec)
    public.pop(OWNER_PROGRESS_FIELD, None)
    return public
