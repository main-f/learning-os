# Rae Learning OS — isolated P0 starter

A **working starter prototype**, not the completed Learning OS. It deliberately does not modify or merge the existing `cybersecurity_codex` or Telegram lifestyle assistant projects.

See `docs/ADR-001-project-isolation.md` first. Full personal product requirements are kept outside this starter; see `docs/PRD_REFERENCE.md` (do not publish the personal PRD).

## Architecture

```text
existing tg-box [UNCHANGED]  (optional future /study adapter)

existing cybersecurity_codex [READ ONLY]
          | local COURSE_ROOT
          v
rae-learning-os/
  services/study_core/       FastAPI + SQLite + independent Study Telegram Bot
  apps/web/                  React + Vite, /#/play and /#/dashboard
  docs/                      requirements and boundaries
  .github/workflows/pages.yml  MANUAL public-shell deploy only
```

## 1. Start the local study API

On the always-on PC, create a Python virtualenv (Python 3.11+):

```bash
cd services/study_core
python -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\\Scripts\\Activate.ps1
pip install -r requirements.txt
export LEARNING_OS_DB="$PWD/data/learning.sqlite"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8765
```

This intentionally listens on **127.0.0.1 only**. Do not port-forward 8765 or expose this unauthenticated prototype to the Internet.

Try: `http://127.0.0.1:8765/health` and `http://127.0.0.1:8765/api/v1/summary`.

## 2. Start the local web UI

In a second terminal (Node 20+):

```bash
cd apps/web
npm install
npm run dev
```

Open `http://127.0.0.1:5173/#/dashboard` or `/#/play`. Vite proxies `/api` only while developing locally. The browser demo game is explicitly not an actual exam or proof of learning.

## 3. Import existing course topic metadata, read-only

```bash
cd services/study_core
export COURSE_ROOT=/absolute/path/to/cybersecurity_codex
export LEARNING_OS_DB="$PWD/data/learning.sqlite"
python -m app.import_topics
```

This reads only the canonical `maso/NN-N_*.md` topic files. It records relative path and SHA-256, **not** the full content or academic score. The actual course question importer, answer validation and `GradeCalc.xlsx` tests are the next milestone.

## 4. Independent Study Telegram Bot (optional until credentials are available)

Use BotFather to create a **new** bot, distinct from your lifestyle assistant. Get your own Telegram numeric chat ID through a trusted local method, and restrict the Bot to that chat. Set credentials **only on your local PC**; never commit them.

```bash
cd services/study_core
export STUDY_TELEGRAM_BOT_TOKEN='YOUR_NEW_STUDY_BOT_TOKEN'
export STUDY_TELEGRAM_ALLOWED_CHAT_ID='YOUR_NUMERIC_TELEGRAM_CHAT_ID'
export LEARNING_OS_DB="$PWD/data/learning.sqlite"
python -m app.study_bot
```

Commands: `/today` (send next pending task), `/done <what you actually did>` (self-reported task completion). Separate process and database mean the existing lifestyle assistant remains intact.

To send one reminder from the host PC scheduler:

```bash
python -m app.notify_today
```

Use host `cron`, macOS `launchd` or Windows Task Scheduler. Schedule reminders *and AI planner* separately. The starter doesn't enable recurring schedules automatically.

## 5. Run tests

```bash
cd services/study_core
pip install pytest httpx
python -m pytest -q
```

## Public GitHub Pages caveat

The manual GitHub Pages workflow deploys **only the web UI**, which defaults to demonstration mode in production. GitHub Pages is public even when the repository is private under eligible plans. Never publish SQLite, real grades, source PDFs, tokens or recordings without reviewing sharing rights. Real mobile read/write sync needs authenticated backend, not directly writing into GitHub Pages.

## Build verification

Backend automated tests pass. Frontend installation/build could not be verified in the sandbox because package registry access timed out; run `npm install && npm run build` on your own PC before any Pages deployment.

## What this starter doesn't do yet

It does **not** connect NotebookLM, produce daily podcasts, calculate Grade 5 predictions, automatically update from external Codex chats, or implement auth/remote database synchronization. Those are P1/P2 milestones in `docs/ROADMAP.md`.

For prompt safety, a future background `codex exec` job should use a separate work directory and restricted sandbox. Review `docs/ADR-001-project-isolation.md` before setting up unattended jobs.
