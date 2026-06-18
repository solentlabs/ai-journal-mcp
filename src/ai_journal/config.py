"""Load journal sources from journals.toml."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG = Path("~/.config/ai-journal/journals.toml").expanduser()
DEFAULT_DB = Path("~/.local/share/ai-journal/index.db").expanduser()


@dataclass
class JournalSource:
    name: str
    path: Path
    mode: str  # "managed" | "indexed"


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
