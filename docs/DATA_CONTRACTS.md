# Data and API contracts

## Import contract

- Stable ID: `course_id:topic_id:q<local_number>`.
- Markdown prompt and four repeated-`1.` options preserve source order.
- Markdown answer field, learner reasoning, and official correct options are separate columns.
- `source_verified` requires an exact normalized prompt, ordered-option match, legal saved-page answer number, and answer-title text matching that option.
- Every imported real question is `private_only`; the private report contains counts/IDs/paths, never prompt text.

## Game contract

- `GET /api/v1/game-config`: active private set/ruleset metadata and whether the complete Chinese translation set is human-verified; it returns no question text.
- `POST /api/v1/game-sessions/start`: accepts `assistance_mode=none|zh_translation`; creates a ruleset-v2 session with a random seed and persisted question/option presentation order. It never returns correct answers.
- `POST /api/v1/game-sessions/{id}/attempts`: submits stable opaque option tokens rather than display indexes. The server maps tokens to canonical options, scores, and atomically writes attempt, presentation order, assistance mode, reward, session totals, and outbox event.
- `POST /api/v1/game-sessions/{id}/complete`: requires all ten attempts and stores one unique completion event.
- `GET /api/v1/game-sessions/{id}/result`: saved session, fixed presentation order, attempts, assistance data, raw time, multiplier, and ranked time. Active sessions can be restored without reshuffling or resetting their server start time.
- `GET /api/v1/dashboard`: import counts, latest completed game, same-set/same-rules Personal Best, and academic unknown states.

Attempt and completion `event_id` values are unique. Replaying the same event with the same payload returns the stored response; reusing it for different data returns `409`. Ruleset v2 Personal Best orders by `correct_count DESC`, then `ranked_duration_ms ASC` within the exact question-set and ruleset versions. Ruleset-v1 records remain stored but never mix with v2.

`raw_duration_ms` is authoritative server elapsed time. `time_multiplier` is `1.0` for no assistance and `1.3` for Chinese translation assistance. `ranked_duration_ms = round(raw_duration_ms × time_multiplier)`. SQLite and APIs use integer milliseconds; the browser renders `MM:SS.mmm` from a monotonic clock while playing.

Questions may contain private `prompt_zh`, `options_zh_json`, `translation_status`, `translation_version`, and `translation_reviewed_at`. Draft translations are never returned by gameplay APIs. `zh_translation` start requests fail unless every active-set translation is `human_verified`; English always remains present. Assisted attempts are explicitly marked and cannot silently become unassisted Mastery evidence.

XP is deterministic: wrong = 0; correct = 10 plus a bounded streak bonus (maximum 18 per question). XP never writes Official grade or Mastery. Unreviewed explanations return `详细解析待人工复核`.

## SQLite ownership

`schema_migrations`, `questions`, `question_sets`, `game_sessions`, `question_attempts`, `reward_events`, `event_outbox`, and `import_runs` are Study Core private tables. Incremental migrations preserve v1 history. Translation review packs and runtime databases live under ignored `services/study_core/data/`; neither English questions nor Chinese translations may enter web source or public build output.

