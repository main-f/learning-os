# ADR-001 — Keep Study, Life and Course Materials Independent
Status: accepted for starter prototype (2026-11-11)

## Decision

Three separate Git repositories/services:

1. `cybersecurity_codex`: course content, personal study notes and historical plans. **Read-only dependency** to Learning OS. Do not copy raw PDF/audio into any public website.
2. Existing Telegram lifestyle assistant (TG Box): keep code, health/wearable storage, configuration and Codex rules unchanged. No direct access to the learning database.
3. `rae-learning-os`: its own backend, database, Study Bot process and web UI. Owns study planning, verified records, challenges, rewards and generated podcast jobs.

The first pilot runs a **separate Study Telegram Bot with a different token**. Never start two `getUpdates` pollers with one token. If the single-bot experience is desired later, the existing lifestyle bot may call `127.0.0.1` study APIs through a narrowly scoped command adapter instead, without accessing the study DB.

## Boundaries

- Data: `data/learning.sqlite` is study-only. Health and wearables are explicitly excluded.
- Process: distinct service + environment variables + separate log rotation. A learning crash must not terminate the life bot.
- Agent: Codex `-C` points at Learning OS workspace; course repo is mounted read-only and not writable. No blanket `danger-full-access`.
- Interface: `/api/v1/...` versioned API and `event_outbox` record; never attach to the other application's internal SQLite tables.
- Web: GitHub Pages is publicly accessible. Frontend package contains no credentials, course copyright material, private schedule, personal results, or unpublished audio. Read/write of real user data requires a future authenticated API.
- Human control: agents recommend lesson sequences. They cannot fabricate official grades, upload private sources or submit official coursework.

## Practical communication modes

A. *Prototype:* independent Study Bot long-polls Telegram and writes study-only SQLite; front-end runs locally on Vite and reads loopback API.

B. *Production:* public static front-end shell on GitHub Pages; authenticated backend/BaaS for private read/write; home server uses outbound sync. The secure data layer is a separate implementation milestone, not included in this starter.

C. *Later optional single-bot UX:* life bot dispatches `/study` via allowlisted, authenticated local API; study engine remains a separate process and DB. Ensure `/life` and `/study` messages have explicit routing.

## Tradeoffs

Separate Study Bot uses another Telegram chat, but gives maximum safety and independence today. One Bot with plugin feels seamless, but requires knowing and modifying the existing project's language/framework and routing logic.

## Falsifiability / acceptance tests

- Stopping Study Bot doesn't stop the existing bot.
- Study Bot does not read Mi Fitness/health environment variables.
- Learning importer changes no files in `cybersecurity_codex`.
- Demo game XP never changes academic grade or actual readiness.
- Production Pages artifacts contain no `/api` credentials or private score exports.
