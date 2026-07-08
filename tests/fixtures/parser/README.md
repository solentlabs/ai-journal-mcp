# Parser fixtures

Real-world journal formats the parser must handle. `test_parser.py` discovers
every `*.md` here, parses it, and asserts against its sibling
`*.expected.json` — one parametrized test case per fixture, named by file stem.

**To add a format** (e.g. a new header style you found in the wild), drop in:

- `my_case.md` — the raw markdown, exactly as encountered.
- `my_case.expected.json` — what the parser should produce.

No test code changes. This satisfies the `CLAUDE.md` rule that parser changes
ship with a fixture reproducing the format that motivated them.

## `*.expected.json` schema

```jsonc
{
  "description": "human note on what this fixture exercises",
  "header": "^### \\[(?P<date>...",  // optional; extraction-spec header regex
                                     // for foreign formats (named groups:
                                     // date required, time/title optional)
  "date_format": "%Y-%m-%d",         // optional; strptime format for the date
  "entries": [
    {
      "date": "2026-06-11",          // required, ISO; entry.date.isoformat()
      "time": "10:42",               // optional; use null to assert no time
      "title": "First Entry",        // optional; use null to assert no title
      "header_level": 3,             // optional; markdown header depth
      "body": "exact body",          // optional; exact-match assertion
      "body_contains": ["substr"],   // optional; each must appear in the body
      "body_endswith": "tail."       // optional; body must end with this
    }
  ]
}
```

`entries` length is asserted (so over- and under-parsing both fail). An empty
`entries` array asserts the file yields no entries.
