"""Load journal sources from journals.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from .fsio import write_text_atomic

DEFAULT_CONFIG = Path("~/.config/ai-journal-mcp/journals.toml").expanduser()
DEFAULT_DB = Path("~/.local/share/ai-journal-mcp/index.db").expanduser()
# Per-session auto-capture counters. State, not data: disposable, machine-local,
# and never part of a journal.
DEFAULT_STATE_DIR = Path("~/.local/state/ai-journal-mcp/capture").expanduser()


@dataclass
class JournalSource:
    name: str
    path: Path
    mode: str  # "managed" | "indexed"


@dataclass
class CaptureConfig:
    """The ``[capture]`` table of journals.toml — auto-capture tuning."""

    enabled: bool = True
    min_turns: int = 8


def load_capture_config(config_path: Path | None = None) -> CaptureConfig:
    """Read ``[capture]`` from journals.toml, falling back to the defaults.

    A missing file or a missing/!mapping table is not an error: auto-capture is
    opt-in by *installing the hook*, so an untuned config must still work. Only
    keys that are present override, and a wrong-typed value is ignored rather
    than raising — a hook runs on every turn and must never wedge a session over
    a typo in a config it didn't need.
    """
    path = config_path or DEFAULT_CONFIG
    defaults = CaptureConfig()
    if not path.exists():
        return defaults
    try:
        table = tomllib.loads(path.read_text(encoding="utf-8")).get("capture", {})
    except (OSError, tomllib.TOMLDecodeError):
        return defaults
    if not isinstance(table, dict):
        return defaults
    enabled = table.get("enabled", defaults.enabled)
    min_turns = table.get("min_turns", defaults.min_turns)
    return CaptureConfig(
        enabled=enabled if isinstance(enabled, bool) else defaults.enabled,
        # bool is an int subclass; `min_turns = true` is a mistake, not a 1
        min_turns=min_turns if isinstance(min_turns, int) and not isinstance(min_turns, bool) else defaults.min_turns,
    )


def load_config(config_path: Path | None = None) -> list[JournalSource]:
    path = config_path or DEFAULT_CONFIG
    if not path.exists():
        raise FileNotFoundError(
            f"No config at {path}. Create it with [[journal]] entries (name, path, mode = 'managed' or 'indexed')."
        )
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    sources = []
    for raw in data.get("journal", []):
        sources.append(
            JournalSource(
                name=raw["name"],
                path=Path(raw["path"]).expanduser(),
                mode=raw.get("mode", "indexed"),
            )
        )
    return sources


def _toml_str(value: str) -> str:
    """Quote a value as a TOML basic string (a quote or backslash in a journal
    name/path must not corrupt journals.toml — every later load would fail).
    Control characters are rejected outright: TOML basic strings forbid them,
    and a journal named with an embedded newline is a mistake, not a case to
    round-trip."""
    if any(ord(ch) < 0x20 or ord(ch) == 0x7F for ch in value):
        raise ValueError(f"journal name/path may not contain control characters: {value!r}")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def add_journal(
    name: str,
    path: Path,
    mode: str = "managed",
    config_path: Path | None = None,
) -> bool:
    """Append a ``[[journal]]`` stanza to journals.toml, creating it if absent.

    Returns False (changing nothing) if a journal with this name is already
    configured. The path is written verbatim; ``load_config`` expands it.
    """
    cfg = config_path or DEFAULT_CONFIG
    if cfg.exists():
        if any(src.name == name for src in load_config(cfg)):
            return False
        existing = cfg.read_text(encoding="utf-8").rstrip("\n")
        prefix = f"{existing}\n\n" if existing else ""
    else:
        cfg.parent.mkdir(parents=True, exist_ok=True)
        prefix = ""
    stanza = f"[[journal]]\nname = {_toml_str(name)}\npath = {_toml_str(str(path))}\nmode = {_toml_str(mode)}\n"
    write_text_atomic(cfg, prefix + stanza)
    return True
