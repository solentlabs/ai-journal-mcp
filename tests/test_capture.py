"""Auto-capture: the nudge decision, its state, and the hook's failure modes."""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from ai_journal_mcp import capture
from ai_journal_mcp.cli import main
from ai_journal_mcp.config import load_capture_config

JOURNALS_TOML = '[[journal]]\nname = "tech"\npath = "{path}"\nmode = "managed"\n'


@pytest.fixture
def capture_env(tmp_path: Path, make_journal):
    """A configured managed journal plus an isolated state dir.

    Returns ``(stop, state_dir, config_path)`` where ``stop(session, n=1)`` runs
    ``n`` Stop events and returns the last nudge (or None) — the shape almost
    every test below wants.
    """
    root = make_journal({"entries/2026-06/01-seed.md": "---\ndate: '2026-06-01'\ntitle: Seed\n---\n\nBody.\n"})
    config_path = tmp_path / "journals.toml"
    config_path.write_text(JOURNALS_TOML.format(path=root), encoding="utf-8")
    state_dir = tmp_path / "state"

    def _stop(session: str = "s1", n: int = 1) -> str | None:
        nudge = None
        for _ in range(n):
            nudge = capture.handle_event(
                {"hook_event_name": "Stop", "session_id": session},
                state_dir=state_dir,
                config_path=config_path,
            )
        return nudge

    return _stop, state_dir, config_path


def test_no_nudge_below_the_turn_threshold(capture_env):
    stop, state_dir, _ = capture_env
    assert stop(n=7) is None
    assert capture.read_state(state_dir / "s1.json").turns == 7


def test_nudge_once_at_the_threshold(capture_env):
    stop, state_dir, _ = capture_env
    assert stop(n=7) is None
    nudge = stop(n=1)
    assert nudge is not None
    assert "8 turns" in nudge
    assert capture.read_state(state_dir / "s1.json").nudged is True
    # an unanswered nudge must not repeat — no coercion needed to make it stick
    assert stop(n=5) is None


def test_journaling_suppresses_the_nudge(capture_env):
    stop, state_dir, config_path = capture_env
    stop(n=4)
    capture.handle_event(
        {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "mcp__ai-journal-mcp__add_entry"},
        state_dir=state_dir,
        config_path=config_path,
    )
    assert capture.read_state(state_dir / "s1.json").journaled is True
    assert stop(n=20) is None


def test_other_tools_do_not_count_as_journaling(capture_env):
    stop, state_dir, config_path = capture_env
    capture.handle_event(
        {"hook_event_name": "PostToolUse", "session_id": "s1", "tool_name": "Edit"},
        state_dir=state_dir,
        config_path=config_path,
    )
    assert capture.read_state(state_dir / "s1.json").journaled is False
    assert stop(n=8) is not None


def test_sessions_do_not_share_a_counter(capture_env):
    stop, _, _ = capture_env
    assert stop(session="a", n=7) is None
    assert stop(session="b", n=7) is None  # b's own 7th turn, not the 14th overall
    assert stop(session="a", n=1) is not None


def test_session_end_drops_the_state_file(capture_env):
    stop, state_dir, config_path = capture_env
    stop(n=3)
    assert (state_dir / "s1.json").exists()
    capture.handle_event(
        {"hook_event_name": "SessionEnd", "session_id": "s1"}, state_dir=state_dir, config_path=config_path
    )
    assert not (state_dir / "s1.json").exists()


def test_no_nudge_without_a_managed_journal(tmp_path, make_journal):
    root = make_journal({"notes.md": "## 2026-06-01: Note\n\nBody.\n"})
    config_path = tmp_path / "journals.toml"
    config_path.write_text(f'[[journal]]\nname = "ro"\npath = "{root}"\nmode = "indexed"\n', encoding="utf-8")
    for _ in range(20):
        nudge = capture.handle_event(
            {"hook_event_name": "Stop", "session_id": "s1"}, state_dir=tmp_path / "state", config_path=config_path
        )
    assert nudge is None  # nudging a user with nowhere to write is advice they can't take


def test_disabled_in_config(capture_env):
    stop, _, config_path = capture_env
    config_path.write_text(config_path.read_text() + "\n[capture]\nenabled = false\n", encoding="utf-8")
    assert stop(n=20) is None


def test_min_turns_is_configurable(capture_env):
    stop, _, config_path = capture_env
    config_path.write_text(config_path.read_text() + "\n[capture]\nmin_turns = 2\n", encoding="utf-8")
    assert stop(n=1) is None
    assert stop(n=1) is not None


@pytest.mark.parametrize(
    "table,expected",
    [
        ("", (True, 8)),  # no [capture] table at all
        ("[capture]\nenabled = false\n", (False, 8)),
        ("[capture]\nmin_turns = 3\n", (True, 3)),
        ("[capture]\nmin_turns = true\n", (True, 8)),  # bool is an int subclass; not a 1
        ("[capture]\nmin_turns = 'lots'\n", (True, 8)),
        ("[capture]\nenabled = 'yes'\n", (True, 8)),
        ("capture = 5\n", (True, 8)),  # not even a table
        ("[capture\nmin_turns = 3\n", (True, 8)),  # unparseable TOML
    ],
)
def test_capture_config_ignores_junk(tmp_path, table, expected):
    path = tmp_path / "journals.toml"
    path.write_text(table, encoding="utf-8")
    config = load_capture_config(path)
    assert (config.enabled, config.min_turns) == expected


def test_capture_config_defaults_without_a_config_file(tmp_path):
    config = load_capture_config(tmp_path / "absent.toml")
    assert (config.enabled, config.min_turns) == (True, 8)


@pytest.mark.parametrize("session_id", ["../escape", "a/b", ".hidden", "", "a\0b"])
def test_path_like_session_ids_are_rejected(session_id, tmp_path):
    # the id becomes a filename; it must never resolve outside the state dir
    with pytest.raises(ValueError, match="invalid session id"):
        capture.state_path(session_id, tmp_path)


@pytest.mark.parametrize("corrupt", ["{not json", "[]", "null", '"a string"'])
def test_corrupt_state_restarts_from_zero(corrupt, capture_env):
    stop, state_dir, _ = capture_env
    stop(n=3)
    (state_dir / "s1.json").write_text(corrupt, encoding="utf-8")
    stop(n=1)
    assert capture.read_state(state_dir / "s1.json").turns == 1


def test_unreadable_journals_toml_never_nudges(tmp_path):
    # a broken config must read as "no managed journal", not raise into the turn
    config_path = tmp_path / "journals.toml"
    config_path.write_text("[[journal]\nname = broken\n", encoding="utf-8")
    for _ in range(20):
        nudge = capture.handle_event(
            {"hook_event_name": "Stop", "session_id": "s1"}, state_dir=tmp_path / "state", config_path=config_path
        )
    assert nudge is None


def test_unknown_events_and_bad_payloads_are_ignored(capture_env):
    stop, state_dir, config_path = capture_env
    for event in ({"hook_event_name": "PreCompact", "session_id": "s1"}, {"hook_event_name": "Stop"}, {}):
        assert capture.handle_event(event, state_dir=state_dir, config_path=config_path) is None
    assert not (state_dir / "s1.json").exists()


def test_hook_cli_emits_claude_code_json(capture_env, monkeypatch, capsys):
    """End to end through the real entry point Claude Code invokes."""
    stop, state_dir, config_path = capture_env
    stop(n=7)
    # the CLI passes no paths, so point the module defaults at the fixture
    monkeypatch.setattr(capture, "DEFAULT_STATE_DIR", state_dir)
    monkeypatch.setattr("ai_journal_mcp.config.DEFAULT_CONFIG", config_path)
    monkeypatch.setattr("sys.stdin", io.StringIO('{"hook_event_name":"Stop","session_id":"s1"}'))

    assert main(["hook"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["hookSpecificOutput"]["hookEventName"] == "Stop"
    assert "worth recalling" in payload["hookSpecificOutput"]["additionalContext"]


@pytest.mark.parametrize("stdin_text", ["", "not json at all", "[]", "null", '{"hook_event_name":"Stop"}'])
def test_hook_cli_never_fails_a_turn(stdin_text, monkeypatch, capsys):
    # a hook that errors puts a notice in front of the user every turn — worse
    # than auto-capture quietly not firing
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin_text))
    assert main(["hook"]) == 0
    assert capsys.readouterr().out == ""
