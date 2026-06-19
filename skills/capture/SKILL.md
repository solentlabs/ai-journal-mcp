---
name: capture
description: Capture a work-session insight, lesson, decision, or "this could be a blog post" moment into an ai-journal managed journal via the add_entry MCP tool. Use when the user says to journal/log/record something, or at the end of a session worth remembering. Journal-agnostic — works with whatever journals are configured.
---

# ai-journal — Capture

Turn something worth keeping — a debugging pattern, a process lesson, a
decision, a "this could be a post" idea — into a canonical journal entry.
Capture must be cheaper than not capturing: draft the entry *for* the user from
the conversation; never make them format it.

## When to use

- The user says "journal this," "log it," "add an entry," or similar.
- A session ends with a lesson, pattern, or insight worth recalling later.
- Something surfaces that's blog or talk material.

## How to capture

1. **Pick the journal.** Only `managed` journals accept entries. If exactly one
   is configured, use it. If several (e.g. a journal per project), ask which.
   `list_themes` shows the configured journals and their themes.
2. **Draft the entry** from the conversation:
   - `title` — concise and specific (a future search matches on it).
   - `body` — freeform: a whole-session dump, a single lesson, or a tidied-up
     list are all valid. This is the substance.
   - `themes` — the topic(s) it belongs to. If the user named none, call
     `suggest_themes(title + body)` and propose what it returns (existing themes
     ranked by similarity); confirm, then use those. Reuse existing themes so
     pattern-finding stays coherent; add a new one only when nothing fits.
     Multi-valued.
   - `tags` — optional finer labels.
   - `blog_angles` — when the insight is post-worthy, propose one or more angles
     (working titles). This is the raw material for later writing; don't let it
     evaporate.
   - `entry_date` — defaults to today; set only when backdating.
3. **Write it** with `add_entry(journal, title, body, themes?, tags?,
   blog_angles?, entry_date?)`. One call writes the entry, regenerates the
   views, and rebuilds the index.
4. **Confirm** the returned path and the themes used.

## Principles

- Capture freely; structure (path, frontmatter, views) is the tool's job.
- Reuse existing themes over inventing near-duplicates.
- Flag post-worthy insights through `blog_angles`, not prose.
