"""Auto-capture: decide whether a session should be nudged to journal.

Recall is worthless against entries that were never written, and capture
competes with the work at exactly the moment the user is deepest in it. An MCP
server cannot close that gap — it only responds, it cannot start a turn — so
the trigger is a Claude Code hook that calls in here once per assistant turn.

This module decides; it never writes an entry. The nudge points the model at
the capture skill, which drafts one and confirms with the user. Entries are
append-only with no delete tool, so a false-positive auto-entry would be
permanent, while a nudge that misfires costs one line of context. See the
auto-capture ADR.

No transcript parsing: the ``Stop`` hook firing *is* the turn counter, and a
``PostToolUse`` matcher scoped to ``add_entry`` alone sets the journaled flag.
Nothing here depends on the shape of Claude Code's transcript files.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .config import DEFAULT_STATE_DIR, load_capture_config, load_config

# A session id becomes a filename. Same discipline as task ids: no separators
# anywhere and no leading dot, so a hostile or malformed id can never resolve
# outside the state directory.
_SESSION_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

NUDGE = (
    "[ai-journal-mcp] This session has run {turns} turns without a journal entry.\n"
    "At the next natural pause — not mid-task — consider whether it taught something "
    "worth recalling later: a lesson, a decision and why, a pattern, or blog material. "
    "If so, offer to capture it with add_entry (the `capture` skill covers drafting, "
    "themes, and confirmation). If nothing here is worth keeping, ignore this and "
    "carry on; it will not ask again this session."
)


@dataclass
class CaptureState:
    """Per-session counters behind the nudge decision."""

    turns: int = 0
    journaled: bool = False
    nudged: bool = False


def state_path(session_id: str, state_dir: Path | None = None) -> Path:
    """Path of a session's state file. Raises ValueError on an unusable id."""
    if not _SESSION_ID.fullmatch(session_id):
        raise ValueError(f"invalid session id {session_id!r}")
    return (state_dir or DEFAULT_STATE_DIR) / f"{session_id}.json"


def read_state(path: Path) -> CaptureState:
    """Load a session's state; a missing or corrupt file restarts from zero
    (it is disposable counters, not data — never a reason to fail a turn)."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return CaptureState()
    if not isinstance(raw, dict):
        return CaptureState()
    turns = raw.get("turns", 0)
    return CaptureState(
        turns=turns if isinstance(turns, int) and not isinstance(turns, bool) else 0,
        journaled=bool(raw.get("journaled", False)),
        nudged=bool(raw.get("nudged", False)),
    )


def write_state(path: Path, state: CaptureState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state.__dict__), encoding="utf-8")


def _has_managed_journal(config_path: Path | None) -> bool:
    """True when some journal can actually accept an entry. Nudging a user with
    no managed journal would be advice they cannot take."""
    try:
        return any(src.mode == "managed" for src in load_config(config_path))
    except (FileNotFoundError, OSError, KeyError, ValueError):
        return False


def handle_event(
    event: dict,
    state_dir: Path | None = None,
    config_path: Path | None = None,
) -> str | None:
    """Process one Claude Code hook event; return nudge text, or None.

    ``Stop`` counts the turn and decides. ``PostToolUse`` (matched to
    ``add_entry``) records that this session journaled. ``SessionEnd`` drops the
    state file. Any other event is ignored.
    """
    session_id = event.get("session_id")
    if not isinstance(session_id, str) or not session_id:
        return None
    path = state_path(session_id, state_dir)
    name = event.get("hook_event_name")

    if name == "SessionEnd":
        path.unlink(missing_ok=True)
        return None

    if name == "PostToolUse":
        # matcher-scoped in settings.json, re-checked here so a broader matcher
        # can't silently switch auto-capture off for the session
        if str(event.get("tool_name", "")).split("__")[-1] == "add_entry":
            state = read_state(path)
            state.journaled = True
            write_state(path, state)
        return None

    if name != "Stop":
        return None

    config = load_capture_config(config_path)
    state = read_state(path)
    state.turns += 1
    due = (
        config.enabled
        and not state.journaled
        and not state.nudged
        and state.turns >= config.min_turns
        and _has_managed_journal(config_path)
    )
    if due:
        state.nudged = True  # at most one nudge per session, answered or not
    write_state(path, state)
    return NUDGE.format(turns=state.turns) if due else None
