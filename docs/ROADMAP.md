# v0.3 implementation roadmap

1. **P0-A — Real question import and source verification.** Read-only Markdown parsing, saved-page reconciliation, private report, and a deterministic 10-question set.
2. **P0-B — Speed Run, streak, XP, and Personal Best.** Server-authoritative scoring; correctness ranks before speed; XP remains non-academic.
   - **P0-B.1 — Game Feel, Randomization & Chinese Assistance.** Original lightweight success motion, millisecond timing, server-persisted question/option shuffles, stable option tokens, resumable sessions, and an optional reviewed Chinese-assistance mode with ranked-time penalty.
3. **P0-C — SQLite and Dashboard.** Immutable attempts, idempotent completion, recent result, same-version Personal Best, and explicit unknown academic state.
4. **P0-D — Later Telegram private deep link.** A separate Study Bot may open the private challenge only after access and token boundaries are approved.

P0-B.1 must be completed before P0-D. Chinese assistance remains unavailable until all translations in the active private set are explicitly human-approved. Boss Battle, knowledge tree, remote auth, GradeCalc, multiplayer ranking, and public deployment are outside this slice.
