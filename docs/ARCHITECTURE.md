# Architecture — v0.3 local slice

```text
cybersecurity_codex (read only)
  Markdown topics + two saved MASO pages
                 |
                 v
private importer / mechanical reconciliation
                 |
                 v
SQLite: questions → versioned question_set → sessions / attempts / rewards / outbox
                 ^                                      |
                 |                                      v
React/Vite  <----+---- loopback FastAPI ----> Dashboard / Personal Best
```

Study Core owns all scoring and persistence. The browser receives prompts and ordered options at start, but receives correct options only after a successful attempt write. Completion is acknowledged only after the SQLite transaction commits.

The runtime is local-only (`127.0.0.1`, default port `8876`). `health-monitor` is not imported or modified. Static web assets are a public-safe shell: private questions, SQLite, results, and audio never enter source or `dist`.

All persisted timestamps are UTC. The browser formats them using `Europe/Helsinki`. AI is not part of answer verification, scoring, XP, Personal Best, Official grade, or Mastery state.

