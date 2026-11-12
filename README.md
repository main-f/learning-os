# Rae Learning OS v0.3 — real private MCQ slice

This repository now contains a local, playable vertical slice:

`read-only course import → fixed private 10-question set → Speed Run → server scoring → SQLite → Dashboard + Personal Best`

The course repository remains an external read-only dependency. Real questions, answers, results, SQLite files, import reports, audio, and credentials are private runtime data and are ignored by Git.

## Boundaries

- `cybersecurity_codex`: read-only `COURSE_ROOT`; never copied into the web bundle.
- `health-monitor`: completely separate; its service, database, token, and port are untouched.
- Study Core: loopback only at `127.0.0.1:8876` by default.
- Official grade, Mastery, and game XP are independent. This slice keeps Official grade pending and Mastery unknown.
- No Telegram delivery, NotebookLM call, TTS, authentication placeholder, or deployment is performed here.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATA_CONTRACTS.md](docs/DATA_CONTRACTS.md), and [docs/TEST_PLAN.md](docs/TEST_PLAN.md).

## 1. Configure and import the private course bank

Python 3.11+ is required. Start from `services/study_core`:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
export COURSE_ROOT=/absolute/path/to/cybersecurity_codex
export LEARNING_OS_DB="$PWD/data/learning.sqlite"
python -m app.import_topics
```

The importer reads only the 33 root `maso/NN-N_*.md` topics and the two locally saved MASO question pages. It performs no network access. The private `data/import_report.json` contains counts, IDs, and source paths, but no copied question text.

## 2. Run Study Core

```bash
export LEARNING_OS_HOST=127.0.0.1
export LEARNING_OS_PORT=8876
python -m app.main
```

Health check: `http://127.0.0.1:8876/health`. The launcher rejects any host other than `127.0.0.1`.

## 3. Run the React UI

From `apps/web` (Node 20+):

```bash
npm ci
export VITE_DEV_API_TARGET=http://127.0.0.1:8876
npm run dev
```

Open `http://127.0.0.1:5173/#/play` or `/#/dashboard`. Real prompts and answers are fetched from the local API; none are hardcoded in source or generated public assets.

## 4. Verify

```bash
cd services/study_core
COURSE_ROOT=/absolute/path/to/cybersecurity_codex .venv/bin/python -m pytest -q

cd ../../apps/web
npm run build

cd ../../services/study_core
.venv/bin/python -m app.audit_public_build \
  --dist ../../apps/web/dist \
  --database data/learning.sqlite

cd ../..
git diff --check
```

The real integration test compares `cybersecurity_codex` Git status before and after import. Do not publish `dist` as a working private app: without a separately designed authenticated API it is only a static shell.
