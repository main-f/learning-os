# Data and API contracts

## Import contract

- Stable ID: `course_id:topic_id:q<local_number>`.
- Markdown prompt and four repeated-`1.` options preserve source order.
- Markdown answer field, learner reasoning, and official correct options are separate columns.
- `source_verified` requires an exact normalized prompt, ordered-option match, legal saved-page answer number, and answer-title text matching that option.
- Every imported real question is `private_only`; the private report contains counts/IDs/paths, never prompt text.

## Game contract

- `POST /api/v1/game-sessions/start`: fixed 10-question private set; never returns correct options.
- `POST /api/v1/game-sessions/{id}/attempts`: 1-based chosen option indexes; server scores and atomically writes attempt, reward, session totals, and outbox event.
- `POST /api/v1/game-sessions/{id}/complete`: requires all ten attempts and stores one unique completion event.
- `GET /api/v1/game-sessions/{id}/result`: saved session and attempt results.
- `GET /api/v1/dashboard`: import counts, latest completed game, same-set/same-rules Personal Best, and academic unknown states.

Attempt and completion `event_id` values are unique. Replaying the same event with the same payload returns the stored response; reusing it for different data returns `409`. Personal Best orders by `correct_count DESC`, then `duration_ms ASC` within the exact question-set and ruleset versions.

XP is deterministic: wrong = 0; correct = 10 plus a bounded streak bonus (maximum 18 per question). XP never writes Official grade or Mastery. Unreviewed explanations return `详细解析待人工复核`.

## SQLite ownership

`schema_migrations`, `questions`, `question_sets`, `game_sessions`, `question_attempts`, `reward_events`, `event_outbox`, and `import_runs` are Study Core private tables. `event_outbox` includes an idempotency key, schema version, processing status, error, and processing timestamp. Database files live under ignored `data/`.

