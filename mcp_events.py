# mcp_events.py
#
# Reconstructed module. This file existed in Astrid's working environment
# (freecad_mcp_server.py imports `event_context, emit_event` from it) but was
# never committed to the mcp-free-cad- repo and wasn't found anywhere on disk
# or in the uvx cache — rebuilt from the 6 call-sites already in
# freecad_mcp_server.py:
#
#   with event_context() as _acc:
#       ...
#       emit_event("warn", "response_parse_failed", f"...: {str(_e)[:200]}")
#       emit_event("warn", "image_extract_failed", f"...: {str(_e)[:200]}")
#       emit_event("warn", "instance_enrich_failed", f"...: {str(_e)[:200]}")
#       ...
#       if _acc.has_any("warn"):
#           payload["events"] = _acc.to_envelope("warn")
#
# Design:
#   - event_context() is a context manager. Inside its `with` block, any
#     emit_event() call (even from nested helper functions in the same
#     coroutine) attaches to that block's accumulator, so a single tool call
#     can collect "soft failure" warnings (parse errors, enrichment failures)
#     without raising, and surface them alongside a still-successful result.
#   - Uses contextvars rather than a module-level global/list so concurrent
#     tool calls (this is an asyncio server handling multiple in-flight
#     tools) don't leak events into each other's accumulators.
#   - emit_event() outside any event_context() (shouldn't normally happen
#     given how the server uses it, but defensive) logs to stderr instead of
#     silently discarding, so nothing vanishes if a call-site is ever added
#     outside a `with event_context()` block.

from __future__ import annotations

import contextvars
import sys
from collections import defaultdict
from typing import Any, Dict, List, Optional

_current_accumulator: "contextvars.ContextVar[Optional[EventAccumulator]]" = (
    contextvars.ContextVar("_current_accumulator", default=None)
)


class EventAccumulator:
    """Collects events keyed by level (e.g. "warn") during one `with
    event_context()` block."""

    def __init__(self) -> None:
        self._events: Dict[str, List[Dict[str, str]]] = defaultdict(list)

    def add(self, level: str, code: str, message: str) -> None:
        self._events[level].append({"code": code, "message": message})

    def has_any(self, level: str) -> bool:
        return bool(self._events.get(level))

    def to_envelope(self, level: str) -> List[Dict[str, str]]:
        """Return the accumulated events for `level` as plain dicts, ready
        to attach to a JSON response payload."""
        return list(self._events.get(level, []))

    def all_events(self) -> Dict[str, List[Dict[str, str]]]:
        return {level: list(items) for level, items in self._events.items()}


class _EventContext:
    """The object returned by event_context(); a plain context manager."""

    def __enter__(self) -> EventAccumulator:
        self._acc = EventAccumulator()
        self._token = _current_accumulator.set(self._acc)
        return self._acc

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        _current_accumulator.reset(self._token)
        return False  # never swallow exceptions


def event_context() -> _EventContext:
    """Open a new event-accumulation scope. Use as:

        with event_context() as _acc:
            ...
            emit_event("warn", "some_code", "some message")
            ...
            if _acc.has_any("warn"):
                payload["events"] = _acc.to_envelope("warn")
    """
    return _EventContext()


def emit_event(level: str, code: str, message: str) -> None:
    """Record an event against whichever event_context() is currently open
    in this coroutine/task. If none is open, log to stderr rather than
    silently dropping it."""
    acc = _current_accumulator.get()
    if acc is not None:
        acc.add(level, code, message)
    else:
        print(f"[mcp_events] {level}: {code}: {message}", file=sys.stderr)
