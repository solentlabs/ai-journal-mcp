# 2026-01-23

### [2026-01-23 10:42] Fixed the build pipeline

CI kept failing on the cache step.

#### What actually happened

The cache key was stale. Internal headers must not split the entry.

```
### [2026-01-23 11:00] Not an entry — inside a code fence
```

### [2026-01-23 15:07] Standup notes

Second entry of the day.

### [2026-01-23] Untimed note

A bracketed date with no time still parses; time stays null.
