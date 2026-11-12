# Implementation roadmap

**Vertical slice P0 (included here)**
- Local SQLite schema and FastAPI API with task + session records.
- Read-only importer for flat `maso/*.md` topic metadata, no automatic quiz answers.
- Distinct Study Bot with `/today` + `/done` and one-way scheduled reminders.
- React/Vite local dashboard and tiny clearly-labelled demo game.
- Automated API tests. GitHub Pages deployment workflow is manual, publishing public UI only.

**P1 (implement before real private mobile use)**
- Identity-protected private data API (BaaS with user-level authorization or secured tunnel); cross-device event sync with ID, UTC timestamp, idempotency, queue retries, conflict policy.
- Initial diagnostic test using verified course questions; source citations; item bank dedup + rubric approval.
- A real course task planner reading current dates, actual syllabus, realistic time budget and sleep constraints.
- Manual evidence grading; deterministic exam grade calculator imported from `GradeCalc.xlsx` with tests against actual current rubric.

**P2**
- Audio pipeline from existing A–H prompt library; NotebookLM best-effort adapter with TTS fallback, audio storage, mobile player, background playback testing, saved position; authentication and access controls.
- Time trial, streak, personal best, difficulty, delayed retrieval, error analysis and adaptive questions.
- Two- or three-times-daily orchestration and Telegram gentle escalation; no night-time pressure.

**P3**
- Optional lifestyle bot bridge, independent permissions. Optional wearables and calendar only with explicit consent.

**Non-goals**
- Not a background process running in this generated ZIP.
- Not a production-ready public API or finished authenticated website.
- Does not automate official course submissions or create fictional official grades.
