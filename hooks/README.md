# Auto-capture hook

Journaling depends on someone remembering to journal, at exactly the moment
they are deepest in the work. This hook removes that dependency without taking
the judgment away: after a session has done substantive work with no entry
written, it puts one line in front of the model suggesting a capture. **It
never writes an entry itself** — entries are append-only and there is no delete
tool, so a wrong auto-entry would be permanent, while a nudge that misfires
costs a line of context. The reasoning is in
[`docs/ARCHITECTURE_DECISIONS.md`](../docs/ARCHITECTURE_DECISIONS.md)
("Auto-capture nudges; it never writes").

Installing it is the opt-in. Without it, nothing here runs.

## Install

Merge [`auto-capture.json`](auto-capture.json) into `~/.claude/settings.json`
(or a project's `.claude/settings.json`). If you have no hooks yet, its
`"hooks"` key can be copied in whole; otherwise add each event to the arrays
you already have.

`ai-journal-mcp` must be on the `PATH` Claude Code launches with — the same
binary you registered as the MCP server. Check with:

```bash
ai-journal-mcp hook <<< '{"hook_event_name":"Stop","session_id":"probe"}'
```

That prints nothing (one turn is below the threshold) and exits 0. Run it
`min_turns` times — eight by default — with the same `session_id`, and the last
one prints the nudge JSON. Clean up the probe state the same way a real session
would:

```bash
ai-journal-mcp hook <<< '{"hook_event_name":"SessionEnd","session_id":"probe"}'
```

If it prints nothing on the eighth run, the likely cause is no `managed`
journal in `journals.toml` — auto-capture stays quiet when there is nowhere to
write.

## What each event does

| Event | Why it's needed |
| ----- | --------------- |
| `Stop` | Fires once per assistant turn. It *is* the turn counter — no transcript parsing — and it is the only hook event that can add context to a live session without blocking it. Decides and emits the nudge. |
| `PostToolUse` (matched to `add_entry`) | Records that this session journaled, so a session that already captured is never nudged. Scoped to the one tool, so it costs a process per journal write rather than per tool call. |
| `SessionEnd` | Deletes the session's state file. |

State lives in `~/.local/state/ai-journal-mcp/capture/<session_id>.json` —
turn count, journaled flag, nudged flag. Keyed by session, so concurrent
Claude Code sessions never share a counter. Deleting the directory is always
safe.

## Tuning

Defaults: nudge once per session, after 8 assistant turns, only when a
`managed` journal is configured. Change them in `journals.toml`:

```toml
[capture]
enabled = true      # false disables the nudge without uninstalling the hook
min_turns = 8       # assistant turns before a session is worth capturing
```

Expect to adjust `min_turns` after living with it for a week — too low is
chatty, too high never fires. If it annoys you, `enabled = false` is one line
and the hook stays installed.

## Failure behavior

`ai-journal-mcp hook` is a deliberate no-op on every error — unreadable config,
unwritable state directory, a hook payload a future Claude Code release shapes
differently. It always exits 0 and prints nothing. A hook that errors would put
a notice in front of you on every single turn, which is worse than auto-capture
quietly not firing.

## Portability

This is the one deliberately Claude Code-specific piece of ai-journal-mcp. Hook
APIs are per-client and MCP gives a server no way to start a turn, so there is
no portable version to build. Other clients get manual capture — the `capture`
skill and `add_entry` work everywhere.
