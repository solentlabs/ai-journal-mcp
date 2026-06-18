"""Core data types."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(text: str, max_len: int = 60) -> str:
    slug = _SLUG_RE.sub("-", text.lower()).strip("-")
    if len(slug) > max_len:
        slug = slug[:max_len].rsplit("-", 1)[0]
    return slug or "untitled"


@dataclass
class Entry:
    """A single dated journal entry."""

    date: date
    title: str | None
    body: str
    source_file: Path
    source_line: int
    header_level: int
    themes: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    blog_angles: list[str] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return slugify(self.title or self.body.split("\n", 1)[0][:60] or "untitled")

    @property
    def body_hash(self) -> str:
        """Hash of normalized body, for exact-duplicate detection."""
        normalized = "\n".join(line.rstrip() for line in self.body.strip().splitlines())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    @property
    def identity(self) -> tuple[str, str]:
        """Loose identity for duplicate detection across files."""
        return (self.date.isoformat(), slugify(self.title or "")[:40])
