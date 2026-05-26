"""Safe Python wrappers around `searchfox-cli` for Claude tool-use.

These functions are called by the review loop when Claude asks for additional
context (read a file, find a definition, check callers, etc.) about a
mozilla-central revision under review.

Design notes:

- All functions return a string (possibly long) suitable for stuffing into a
  Claude `tool_result` content block. Errors are returned as text starting
  with "ERROR: " rather than raised — the model can then choose to recover
  (e.g. by guessing a different symbol).
- We cap individual outputs at MAX_OUTPUT_BYTES to keep tokens bounded.
- searchfox-cli does its own on-disk caching, so repeat queries within a
  process (and across processes) are essentially free.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess

log = logging.getLogger(__name__)


SEARCHFOX_CMD = "searchfox-cli"
DEFAULT_TIMEOUT_SECONDS = 30.0
MAX_OUTPUT_BYTES = 16_000  # ~4-5k tokens

# Common locations where `cargo install` / `cargo binstall` / package managers
# drop binaries. Checked in order when `shutil.which` comes up empty — typically
# because PATH is minimal (launchd agents, system services).
_FALLBACK_BIN_DIRS = (
    "~/.cargo/bin",
    "~/.local/bin",
    "/opt/homebrew/bin",
    "/usr/local/bin",
)

# Languages exposed via the --cpp/--js/-c/--webidl/--java/--kt flags.
_LANG_FLAG = {
    "cpp": "--cpp",
    "c": "--c",
    "js": "--js",
    "webidl": "--webidl",
    "java": "--java",
    "kt": "--kt",
}


class SearchfoxUnavailable(RuntimeError):
    pass


def _resolve_searchfox() -> str | None:
    """Return an absolute path to searchfox-cli, or None if not found."""
    found = shutil.which(SEARCHFOX_CMD)
    if found:
        return found
    for d in _FALLBACK_BIN_DIRS:
        candidate = os.path.expanduser(os.path.join(d, SEARCHFOX_CMD))
        if os.access(candidate, os.X_OK):
            return candidate
    return None


def has_searchfox() -> bool:
    """Cheap, non-raising probe for tool availability."""
    return _resolve_searchfox() is not None


def _ensure_available() -> str:
    path = _resolve_searchfox()
    if path is None:
        raise SearchfoxUnavailable(
            "searchfox-cli not found; install with `cargo install searchfox-cli`"
        )
    return path


def _run(args: list[str], *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> str:
    """Run searchfox-cli with the given args. Returns stdout+stderr as text.

    On failure (non-zero exit), returns a string starting with "ERROR: " so the
    model can read it and adjust without us raising.
    """
    cmd_path = _ensure_available()
    try:
        proc = subprocess.run(
            [cmd_path, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return f"ERROR: searchfox-cli timed out after {timeout:.0f}s: {' '.join(args)}"
    except FileNotFoundError as e:
        raise SearchfoxUnavailable("searchfox-cli vanished mid-run") from e

    stdout = proc.stdout or ""
    stderr = proc.stderr or ""

    if proc.returncode != 0:
        # Map common error patterns to friendly text.
        err = stderr.strip() or stdout.strip() or f"exit {proc.returncode}"
        return f"ERROR: searchfox-cli failed: {err[:500]}"

    # Some commands write the actual result to stderr (e.g. when nothing
    # matched). Combine, then truncate.
    out = stdout
    if not out.strip() and stderr.strip():
        out = stderr
    return _truncate(out)


def _truncate(text: str, limit: int = MAX_OUTPUT_BYTES) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    truncated = encoded[:limit].decode("utf-8", errors="ignore")
    return truncated + f"\n\n[... truncated, {len(encoded) - limit} bytes omitted ...]"


def _parse_lines_range(lines: str | None) -> str | None:
    """Pass-through validator for `searchfox-cli --lines` input.

    Accepts forms searchfox-cli supports: '10', '10-20', '10-', '-20'.
    """
    if lines is None:
        return None
    s = lines.strip()
    if not s:
        return None
    # Cheap validation — just confirm only digits/dash.
    if not all(c.isdigit() or c == "-" for c in s):
        raise ValueError(f"invalid line range: {lines!r}")
    return s


# --------------------------------------------------------------------- tools


def read_file(path: str, lines: str | None = None) -> str:
    """Read a file from mozilla-central (optionally a line range)."""
    if not path or path.startswith("/") or ".." in path:
        return f"ERROR: path must be a repo-relative path, got: {path!r}"
    args = ["--get-file", path]
    rng = _parse_lines_range(lines)
    if rng:
        args.extend(["--lines", rng])
    return _run(args)


def find_definition(symbol: str) -> str:
    """Find where a symbol is defined in mozilla-central."""
    if not symbol:
        return "ERROR: symbol is required"
    return _run(["--define", symbol])


def find_callers(symbol: str, depth: int = 1) -> str:
    """List functions that call this symbol."""
    if not symbol:
        return "ERROR: symbol is required"
    depth = max(1, min(int(depth), 3))
    return _run(["--calls-to", symbol, "--depth", str(depth)])


def find_callees(symbol: str, depth: int = 1) -> str:
    """List functions called by this symbol."""
    if not symbol:
        return "ERROR: symbol is required"
    depth = max(1, min(int(depth), 3))
    return _run(["--calls-from", symbol, "--depth", str(depth)])


def search_code(
    query: str,
    *,
    path: str | None = None,
    regex: bool = False,
    language: str | None = None,
    case_sensitive: bool = False,
    exclude_tests: bool = False,
    limit: int = 20,
) -> str:
    """Text or regex search over mozilla-central."""
    if not query:
        return "ERROR: query is required"
    args = ["-q", query, "-l", str(max(1, min(int(limit), 100)))]
    if path:
        args.extend(["-p", path])
    if regex:
        args.append("-r")
    if case_sensitive:
        args.append("-C")
    if exclude_tests:
        args.append("--exclude-tests")
    if language:
        flag = _LANG_FLAG.get(language.lower())
        if flag is None:
            return f"ERROR: unsupported language {language!r}; pick one of {sorted(_LANG_FLAG)}"
        args.append(flag)
    return _run(args)


# --------------------------------------------------------------------- tool registry


TOOL_SCHEMAS = [
    {
        "name": "read_file",
        "description": (
            "Read a file from mozilla-central by repo-relative path. Optionally "
            "limit to a line range. Use this to see the surrounding context of "
            "lines touched by the diff."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repo-relative path, e.g. 'browser/components/ipprotection/foo.cpp'",
                },
                "lines": {
                    "type": "string",
                    "description": "Optional line range: '10', '10-20', '10-' (from), or '-20' (to)",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "find_definition",
        "description": (
            "Find where a symbol is defined in mozilla-central. Use for C++/JS "
            "classes, methods, functions. Supports forms like 'Cls::Method' or "
            "bare names."
        ),
        "input_schema": {
            "type": "object",
            "properties": {"symbol": {"type": "string"}},
            "required": ["symbol"],
        },
    },
    {
        "name": "find_callers",
        "description": (
            "List functions that call the given symbol. Useful for assessing "
            "blast radius when a signature changes."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "find_callees",
        "description": "List functions called by the given symbol.",
        "input_schema": {
            "type": "object",
            "properties": {
                "symbol": {"type": "string"},
                "depth": {"type": "integer", "minimum": 1, "maximum": 3, "default": 1},
            },
            "required": ["symbol"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search mozilla-central for a text or regex pattern. Filter by path "
            "or language. Use this to find related code, usages of a pattern, or "
            "similar implementations elsewhere in the tree."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "path": {
                    "type": "string",
                    "description": "Optional path-prefix filter, e.g. '^browser/components/newtab'",
                },
                "regex": {"type": "boolean", "default": False},
                "language": {
                    "type": "string",
                    "enum": list(_LANG_FLAG.keys()),
                    "description": "Restrict to a language (cpp, c, js, webidl, java, kt)",
                },
                "case_sensitive": {"type": "boolean", "default": False},
                "exclude_tests": {"type": "boolean", "default": False},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 20},
            },
            "required": ["query"],
        },
    },
]


TOOL_DISPATCH = {
    "read_file": read_file,
    "find_definition": find_definition,
    "find_callers": find_callers,
    "find_callees": find_callees,
    "search_code": search_code,
}


def execute_tool(name: str, input_args: dict) -> str:
    """Dispatch a tool call by name. Returns the tool's text output."""
    fn = TOOL_DISPATCH.get(name)
    if fn is None:
        return f"ERROR: unknown tool {name!r}"
    try:
        return fn(**input_args)
    except TypeError as e:
        return f"ERROR: bad arguments for {name}: {e}"
    except SearchfoxUnavailable as e:
        return f"ERROR: {e}"
    except Exception as e:  # last-ditch — return as text so the model can recover
        log.exception("tool %s failed", name)
        return f"ERROR: {type(e).__name__}: {e}"
