"""One-off keyword theming pass for entries migrated without a theme.

Scores each unthemed entry against theme keyword lists (title hits x3,
body hits x1, each keyword capped at 3 body hits). Top theme wins; a
second theme is added if it scores at least half the top. Entries below
threshold stay unthemed for human review.

Usage: python assign_themes.py <managed-journal-root> [--apply]
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import yaml

THEME_KEYWORDS: dict[str, list[str]] = {
    "cable-modem-monitor": [
        "modem",
        "hnap",
        "docsis",
        "channel",
        "ofdm",
        "cmm",
        "hacs",
        "parser",
        "s33",
        "mb8611",
        "mb7621",
        "sb6190",
        "sb6183",
        "sb8200",
        "cm1200",
        "cm2000",
        "cm3500b",
        "cga2121",
        "cga4236",
        "xb7",
        "xb8",
        "xb10",
        "g54",
        "c7000",
        "c3700",
        "arris",
        "netgear",
        "motorola",
        "technicolor",
        "surfboard",
        "firmware",
        "coordinator",
        "fixture",
        "mock server",
        "cable_modem",
        "snmp",
        "downstream",
        "upstream",
        "v3.",
    ],
    "har-capture": [
        "har-capture",
        "har capture",
        "har file",
        "sanitiz",
        "playwright",
        "har replay",
        "tagvaluelist",
    ],
    "development-practices": [
        "workflow",
        "claude",
        "contributor",
        "code review",
        "refactor",
        "pytest",
        "linter",
        "lint",
        "pre-push",
        "ci ",
        "git ",
        "bfg",
        "context summarization",
        "session",
        "skill",
        "test coverage",
        "release process",
        "changelog",
        "ai slop",
        "prompt",
        "wsl",
    ],
    "solentlabs-brand": [
        "website",
        "astro",
        "i18n",
        "linkedin",
        "blog",
        "marketing",
        "brand",
        "outreach",
        "reddit",
        "goatcounter",
        "traffic",
        "solent",
        "product page",
        "community metrics",
        "community snapshot",
        "testimonial",
    ],
    "home-assistant-platform": [
        "home assistant",
        "ha integration",
        "recorder",
        "ha core",
        "honeywell",
        "google_wifi",
        "ha platform",
        "ha-run",
        "entity",
        "automation",
    ],
    "internet-health-monitor": [
        "internet health",
        "outage",
        "latency",
        "hop ",
        "speedtest",
        "isp ",
        "frequency reassignment",
    ],
    "network-investigations": [
        "wireshark",
        "adguard",
        "iot",
        "intelliflow",
        "switched network",
        "protocol analysis",
        "packet",
    ],
    "investment-research": [
        "aif",
        "angel invest",
        "investor",
        "deal research",
        "diligence",
        "compression-algorithm pitch",
        "staysail",
    ],
    "ai-launcher": [
        "launcher",
        "claude-launcher",
    ],
}

THRESHOLD = 2


def classify(title: str, body: str) -> list[str]:
    title_l, body_l = title.lower(), body.lower()
    scores: Counter[str] = Counter()
    for theme, keywords in THEME_KEYWORDS.items():
        for kw in keywords:
            scores[theme] += 3 * title_l.count(kw)
            scores[theme] += min(body_l.count(kw), 3)
    ranked = [(t, s) for t, s in scores.most_common() if s >= THRESHOLD]
    if not ranked:
        return []
    themes = [ranked[0][0]]
    if len(ranked) > 1 and ranked[1][1] >= max(ranked[0][1] // 2, THRESHOLD + 2):
        themes.append(ranked[1][0])
    return themes


def main() -> int:
    root = Path(sys.argv[1]).expanduser()
    apply = "--apply" in sys.argv
    distribution: Counter[str] = Counter()
    changed = 0
    still_unthemed = 0

    for path in sorted((root / "entries").rglob("*.md")):
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            continue
        _, fm, body = text.split("---\n", 2)
        meta = yaml.safe_load(fm)
        if meta.get("themes"):
            continue
        themes = classify(str(meta.get("title") or ""), body)
        if not themes:
            still_unthemed += 1
            continue
        for theme in themes:
            distribution[theme] += 1
        changed += 1
        if apply:
            meta["themes"] = themes
            new_fm = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True)
            path.write_text(f"---\n{new_fm}---\n{body}", encoding="utf-8")

    mode = "APPLIED" if apply else "dry run"
    print(f"{mode}: themed {changed}, still unthemed {still_unthemed}")
    for theme, count in distribution.most_common():
        print(f"  {theme}: {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
