# Repository boundaries

- `cybersecurity_codex` is an external, read-only course dependency. Import from it; never rewrite, format, or generate files in it.
- `health-monitor` and its lifestyle assistant are fully isolated. Do not read its private data, reuse its database, token, process, or port.
- Private question banks, SQLite databases, game results, audio, tokens, cookies, and local `.env` files must never be committed or placed in public web assets.
- Business time is `Europe/Helsinki`; persist timestamps in UTC and convert only for display.
- Official grade, Mastery estimates, and game XP are separate facts. XP must never change an official score or Mastery.
- Local services bind only to `127.0.0.1`, never `0.0.0.0`.

