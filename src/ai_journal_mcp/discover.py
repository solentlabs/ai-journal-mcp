"""Evidence report about an unfamiliar journal directory.

``discover`` makes no parsing decisions. It collects the evidence an LLM (or
a human) needs to write an extraction spec (``spec.py``): where files live,
how they are named, what heading shapes they use, what frontmatter keys
appear, plus a raw excerpt per file family. The intended loop:

    discover → propose a spec → ``scan --spec`` (dry-run) → refine
             → ``migrate --spec --apply`` (originals preserved in attic/)

Shapes are normalized with placeholder tokens (``YYYY-MM-DD``, ``HH:MM``,
``N``, ``slug``, ``Title``) so a thousand daily files collapse into one
pattern line with a real example beside it.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .parser import FENCE_RE

SKIP_DIRS = {".git", ".claude", "attic", "node_modules", ".venv", "__pycache__"}

MAX_HEADING_SHAPES = 20
MAX_NAME_PATTERNS = 20
MAX_EXCERPTS = 6
EXCERPT_LINES = 12

# Greek placeholders: the later passes eat ASCII letters and digits, so a
# placeholder must contain neither; _readable() swaps them for tokens at the end.
_DATE_SUBS = [
    (re.compile(r"\d{4}-\d{2}-\d{2}"), "⟦δ⟧"),
    (re.compile(r"\d{4}/\d{2}/\d{2}"), "⟦ε⟧"),
    (re.compile(r"\d{1,2}:\d{2}(?::\d{2})?"), "⟦τ⟧"),
    (re.compile(r"\d{4}-\d{2}"), "⟦μ⟧"),
]
_NUM_SUB = (re.compile(r"\d+"), "⟦ν⟧")
_TOKENS = {
    "⟦δ⟧": "YYYY-MM-DD",
    "⟦ε⟧": "YYYY/MM/DD",
    "⟦τ⟧": "HH:MM",
    "⟦μ⟧": "YYYY-MM",
    "⟦ν⟧": "N",
}
_PROSE_RE = re.compile(r"[A-Za-z][A-Za-z0-9 ,.'\"&/()_-]*")
_SLUG_RUN_RE = re.compile(r"slug([-_ ]slug)+")
HEADING_RE = re.compile(r"^#{1,6}\s")


def _readable(shape: str) -> str:
    for placeholder, token in _TOKENS.items():
        shape = shape.replace(placeholder, token)
    return shape


def _tokenize_dates(text: str, numbers: bool = True) -> str:
    for pattern, placeholder in _DATE_SUBS:
        text = pattern.sub(placeholder, text)
    if numbers:
        text = _NUM_SUB[0].sub(_NUM_SUB[1], text)
    return text


def _prose_repl(match: re.Match[str]) -> str:
    # keep the run's trailing whitespace so tokens after it stay separated
    text = match.group(0)
    return "Title" + text[len(text.rstrip()) :]


def heading_shape(line: str) -> str:
    """``### [2026-01-23 10:42] Fixed the build`` → ``### [YYYY-MM-DD HH:MM] Title``."""
    shape = _PROSE_RE.sub(_prose_repl, _tokenize_dates(line))
    return _readable(shape.strip())


def filename_shape(name: str) -> str:
    """``2026-01-23-coffee-receipt.md`` → ``YYYY-MM-DD-slug.md``."""
    path = Path(name)
    stem = _tokenize_dates(path.stem, numbers=False)
    parts = []
    for part in re.split(r"([-_. ])", stem):
        if part.startswith("⟦") or part in {"-", "_", ".", " ", ""}:
            parts.append(part)
        elif part.isdigit():
            parts.append("⟦ν⟧")
        else:
            parts.append("slug")  # word-ish, digits inside and all (wsl2, v3)
    shape = _SLUG_RUN_RE.sub("slug", "".join(parts))
    return _readable(shape) + path.suffix


def dir_shape(rel_dir: Path) -> str:
    """``entries/2026-01`` → ``entries/YYYY-MM``; directory names stay verbatim."""
    if not rel_dir.parts:
        return "."
    return _readable("/".join(_tokenize_dates(part) for part in rel_dir.parts))


@dataclass
class DiscoveryReport:
    root: Path
    md_count: int = 0
    other_count: int = 0
    # (dir shape/file shape, count, example relative paths)
    name_patterns: list[tuple[str, int, list[str]]] = field(default_factory=list)
    # (shape, count, raw example line)
    heading_shapes: list[tuple[str, int, str]] = field(default_factory=list)
    frontmatter_files: int = 0
    frontmatter_keys: list[tuple[str, int]] = field(default_factory=list)
    # (relative path, first lines)
    excerpts: list[tuple[str, str]] = field(default_factory=list)


def _frontmatter_keys(text: str) -> list[str]:
    if not text.startswith("---\n"):
        return []
    try:
        _, fm, _ = text.split("---\n", 2)
        meta = yaml.safe_load(fm)
    except (ValueError, yaml.YAMLError):
        return []
    return sorted(meta) if isinstance(meta, dict) else []


def _headings(text: str) -> list[str]:
    lines = []
    in_fence = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
        elif not in_fence and HEADING_RE.match(line):
            lines.append(line.rstrip())
    return lines


def discover(root: Path) -> DiscoveryReport:
    report = DiscoveryReport(root=root)
    pattern_counts: Counter[str] = Counter()
    pattern_examples: dict[str, list[str]] = {}
    pattern_excerpt_file: dict[str, Path] = {}
    shape_counts: Counter[str] = Counter()
    shape_examples: dict[str, str] = {}
    key_counts: Counter[str] = Counter()

    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        is_md = path.suffix.lower() in {".md", ".markdown", ".txt"}
        report.md_count += 1 if is_md else 0
        report.other_count += 0 if is_md else 1

        pattern = f"{dir_shape(rel.parent)}/{filename_shape(path.name)}"
        pattern_counts[pattern] += 1
        pattern_examples.setdefault(pattern, [])
        if len(pattern_examples[pattern]) < 2:
            pattern_examples[pattern].append(str(rel))
        if is_md:
            pattern_excerpt_file.setdefault(pattern, path)
            text = path.read_text(encoding="utf-8", errors="replace")
            for line in _headings(text):
                shape = heading_shape(line)
                shape_counts[shape] += 1
                shape_examples.setdefault(shape, line)
            keys = _frontmatter_keys(text)
            if keys:
                report.frontmatter_files += 1
                key_counts.update(keys)

    report.name_patterns = [
        (pattern, count, pattern_examples[pattern]) for pattern, count in pattern_counts.most_common()
    ]
    report.heading_shapes = [(shape, count, shape_examples[shape]) for shape, count in shape_counts.most_common()]
    report.frontmatter_keys = key_counts.most_common()
    for pattern, _, _ in report.name_patterns:
        if len(report.excerpts) >= MAX_EXCERPTS:
            break
        sample = pattern_excerpt_file.get(pattern)
        if sample is None:
            continue
        lines = sample.read_text(encoding="utf-8", errors="replace").splitlines()[:EXCERPT_LINES]
        report.excerpts.append((str(sample.relative_to(root)), "\n".join(line[:160] for line in lines)))
    return report


_NEXT_STEPS = """\
## Next steps

Write an extraction spec describing where entries live and how dates, times,
and titles are encoded, then dry-run it. The spec is TOML; use single quotes
around regexes so backslashes stay literal:

~~~toml
[[source]]
paths = ["entries/**/*.md"]           # globs relative to the journal root
header = '^###\\s+\\[(?P<date>\\d{4}-\\d{2}-\\d{2})(?:\\s+(?P<time>\\d{2}:\\d{2}))?\\]\\s*(?P<title>.*?)\\s*$'

[[source]]
paths = ["receipts/*.md"]
filename_date = '(?P<date>\\d{4}-\\d{2}-\\d{2})'  # whole file becomes one entry
date_format = "%Y-%m-%d"              # strptime format; this is the default
~~~

Rules: per file, the first matching `[[source]]` wins. `header` (named groups:
`date` required, `time` and `title` optional) splits a file into entries; if
it matches nothing and `filename_date` finds a date in the file name, the
whole file is one entry titled by its first heading. Validate with
`ai-journal-mcp scan ROOT --spec SPEC` (or the scan_source MCP tool, passing
the spec text) until the orphan list holds only files that genuinely are not
entries, then `ai-journal-mcp migrate ROOT --spec SPEC --apply`. Originals
are preserved under attic/; the spec is recorded in migration-report.md."""


def _cell(text: str) -> str:
    """Make arbitrary heading/path text safe inside a markdown table cell."""
    return text.replace("|", "\\|").replace("`", "'")


def format_discovery(report: DiscoveryReport) -> str:
    lines = [
        f"# Discovery: {report.root}",
        "",
        f"{report.md_count} markdown/text files, {report.other_count} other files. "
        "Evidence only — no parsing decisions were made.",
        "",
        "## File name patterns",
        "",
        "| Pattern | Files | Examples |",
        "|---|---|---|",
    ]
    for pattern, count, examples in report.name_patterns[:MAX_NAME_PATTERNS]:
        lines.append(f"| `{_cell(pattern)}` | {count} | {_cell(', '.join(examples))} |")
    if len(report.name_patterns) > MAX_NAME_PATTERNS:
        lines.append(f"| … and {len(report.name_patterns) - MAX_NAME_PATTERNS} more patterns | | |")

    lines += ["", "## Heading shapes", ""]
    if report.heading_shapes:
        lines += ["| Shape | Count | Example |", "|---|---|---|"]
        for shape, count, example in report.heading_shapes[:MAX_HEADING_SHAPES]:
            lines.append(f"| `{_cell(shape)}` | {count} | `{_cell(example[:100])}` |")
        if len(report.heading_shapes) > MAX_HEADING_SHAPES:
            lines.append(f"| … and {len(report.heading_shapes) - MAX_HEADING_SHAPES} more shapes | | |")
    else:
        lines.append("No headings found.")

    lines += ["", "## Frontmatter", ""]
    if report.frontmatter_keys:
        lines.append(f"{report.frontmatter_files} files carry YAML frontmatter. Keys:")
        lines.append("")
        for key, count in report.frontmatter_keys:
            lines.append(f"- `{key}` — {count} files")
    else:
        lines.append("No YAML frontmatter found.")

    if report.excerpts:
        lines += ["", "## Excerpts (one per file family)"]
        for rel, text in report.excerpts:
            fence = "~~~" if "```" in text else "```"
            lines += ["", f"### {rel}", "", fence, text, fence]

    lines += ["", _NEXT_STEPS]
    return "\n".join(lines)
