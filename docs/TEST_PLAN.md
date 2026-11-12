# v0.3 test plan

Unit/API tests use generated synthetic questions only. The opt-in private integration test reads the real `COURSE_ROOT` and asserts 33 topics, 141 candidates, 11 source-verified questions, a 10-question set, and unchanged course-repository Git status.

Coverage includes Markdown parsing, repeated `1.` option order, answer number/text reconciliation, disputed answers, eligibility, answer non-disclosure at start, server scoring, attempt/completion idempotency, streak reset, version-scoped Personal Best, correctness-before-speed ranking, XP/academic isolation, unknown Mastery, read-only import, and public-build leakage.

Required acceptance commands:

```bash
cd services/study_core
COURSE_ROOT=/absolute/path/to/cybersecurity_codex .venv/bin/python -m pytest -q

cd ../../apps/web
npm run build

cd ../../services/study_core
.venv/bin/python -m app.audit_public_build --dist ../../apps/web/dist --database data/learning.sqlite

cd ../..
git diff --check
```

Manual browser checks: touch buttons, number keys + Enter, immediate feedback, correct source, failure/retry wording, final saved state, retry challenge, Dashboard refresh, and mobile layout. No test sends Telegram messages or calls NotebookLM.

