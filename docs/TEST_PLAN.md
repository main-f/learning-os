# v0.3 test plan

Unit/API tests use generated synthetic questions only. The opt-in private integration test reads the real `COURSE_ROOT` and asserts 33 topics, 141 candidates, 11 source-verified questions, a 10-question set, and unchanged course-repository Git status.

Coverage includes the existing import/scoring guarantees plus deterministic seeded shuffles, different-seed variation, option-token scoring after movement, stable session restoration, answer non-disclosure, translation eligibility, reviewed bilingual responses, `1.0`/`1.3` multipliers, ranked-time rounding, ranked-time Personal Best, v1/v2 isolation, assisted-evidence academic isolation, millisecond formatting, monotonic/background timer behavior, success-effect state, reduced-motion fallback, and public-build leakage of English questions, Chinese translations, answers, SQLite, or secrets.

Required acceptance commands:

```bash
cd services/study_core
COURSE_ROOT=/absolute/path/to/cybersecurity_codex .venv/bin/python -m pytest -q

cd ../../apps/web
npm test
npm run build

cd ../../services/study_core
.venv/bin/python -m app.audit_public_build --dist ../../apps/web/dist --database data/learning.sqlite

cd ../..
git diff --check
```

Manual browser checks: two sessions with visibly different question/option orders; millisecond HUD; touch and keyboard controls; fixed bottom action area; positive success motion; reduced-motion mode; refresh/restore without reshuffle; result raw/ranked times; and Dashboard PB. Run an assisted browser session only after the private translation review pack has explicit human approval. No test sends Telegram messages or calls NotebookLM.

