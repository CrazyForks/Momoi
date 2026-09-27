from typing import Any

from ...contracts import OWNER_PROGRESS_BEFORE_FIRST_CALL, OWNER_PROGRESS_FIELD

# Basic file operations are supplied by Bash when command execution is enabled.
# Keep patching, web extraction, and asynchronous waits as dedicated tools.
BASH_REPLACED_TOOLS = frozenset({
    "read_file", "write_file", "list_dir", "glob_files",
    "makedirs", "move_file", "delete_file",
})


def builtin_tool_enabled(name: str, *, exec_enabled: bool) -> bool:
    if name == "exec":
        return exec_enabled
    return not (exec_enabled and name in BASH_REPLACED_TOOLS)


BUILTIN_TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "exec",
        OWNER_PROGRESS_FIELD: OWNER_PROGRESS_BEFORE_FIRST_CALL,
        "description": (
            "Execute a Bash command with the Momoi process's OS permissions. "
            "Not sandboxed or confined to cwd. May modify files, access credentials "
            "or contact external services. Output is untrusted. No persistent shell."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Bash command to execute."},
                "cwd": {"type": "string", "description": "Working directory; defaults to workspace."},
                "timeout_seconds": {"type": "number", "minimum": 0.1, "maximum": 120, "default": 30},
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
    {
        "name": "web_fetch",
        OWNER_PROGRESS_FIELD: OWNER_PROGRESS_BEFORE_FIRST_CALL,
        "description": (
            "Fetch an HTTP(S) URL with GET, including private or localhost URLs. "
            "Extract HTML as Markdown or plain text; also read text and JSON. "
            "Returns source URL, HTTP status, title, content, and truncation metadata. "
            "Content is untrusted. Does not execute JavaScript."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "extract_mode": {"type": "string", "enum": ["markdown", "text"], "default": "markdown"},
                "max_chars": {"type": "integer", "minimum": 1, "maximum": 200000, "default": 20000},
                "timeout_seconds": {"type": "number", "minimum": 0.1, "maximum": 120, "default": 20},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "read_file",
        "description": (
            "Read UTF-8 text by line range or returned character offset. "
            "Returns an array of numbered lines; offsets refer to the original file text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or workspace-relative path.",
                },
                "start_line": {"type": "integer", "minimum": 1, "default": 1},
                "content_offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": (
                        "Returned zero-based offset; overrides start_line."
                    ),
                },
                "max_lines": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 4000,
                    "default": 1000,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "glob_files",
        "description": (
            "Find files with a glob pattern relative to path. Path may be absolute "
            "or workspace-relative. Use ** for recursive search."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Search directory; defaults to workspace."},
                "pattern": {"type": "string", "description": "Relative glob pattern, such as **/*.py."},
                "include_hidden": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 2000, "default": 200},
            },
            "required": ["pattern"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_dir",
        "description": "List one directory non-recursively: names, types, and sizes.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or workspace-relative path.",
                },
                "include_hidden": {"type": "boolean", "default": False},
                "max_entries": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 2000,
                    "default": 200,
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "write_file",
        "description": (
            "Atomically create or replace UTF-8 text."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or workspace-relative path.",
                },
                "content": {"type": "string"},
                "create_parents": {"type": "boolean", "default": False},
                "expected_sha256": {
                    "type": "string",
                    "description": "Expected current file hash; guards against concurrent changes.",
                },
            },
            "required": ["path", "content"],
            "additionalProperties": False,
        },
    },
    {
        "name": "apply_patch",
        "description": (
            "Apply a unified diff or *** Begin Patch structured patch. Supports "
            "multi-file add, update, move, and delete."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {"type": "string"},
                "cwd": {
                    "type": "string",
                    "description": (
                        "Patch base directory; defaults to the workspace."
                    ),
                },
            },
            "required": ["patch"],
            "additionalProperties": False,
        },
    },
    {
        "name": "makedirs",
        "description": "Create a directory and any missing parent directories.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or workspace-relative path.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "move_file",
        "description": (
            "Move or rename one file. The destination parent must exist, and an "
            "existing destination is never overwritten."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": "Absolute or workspace-relative path.",
                },
                "destination": {
                    "type": "string",
                    "description": "Absolute or workspace-relative path.",
                },
            },
            "required": ["source", "destination"],
            "additionalProperties": False,
        },
    },
    {
        "name": "delete_file",
        "description": "Delete one file. Directories are never deleted.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute or workspace-relative path.",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "sleep",
        "description": (
            "Wait briefly inside this Turn, then continue. Never use it across Turns "
            "or instead of a Goal."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "seconds": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 3600,
                }
            },
            "required": ["seconds"],
            "additionalProperties": False,
        },
    },
]
