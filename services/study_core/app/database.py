"""Study-only SQLite storage with small, explicit schema migrations."""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_db_path() -> Path:
    return Path(os.getenv("LEARNING_OS_DB", "data/learning.sqlite")).expanduser().resolve()


def connect() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    db.execute("PRAGMA busy_timeout=10000")
    return db


SCHEMA_V1 = """
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    minutes INTEGER NOT NULL CHECK(minutes > 0),
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'completed')),
    created_at TEXT NOT NULL,
    completed_at TEXT
);

CREATE TABLE IF NOT EXISTS study_sessions (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES tasks(id),
    duration_minutes INTEGER NOT NULL CHECK(duration_minutes >= 0),
    evidence_note TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS course_sources (
    source_id TEXT PRIMARY KEY,
    relative_path TEXT UNIQUE NOT NULL,
    title TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    content_hash TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'personal_notes',
    imported_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS questions (
    question_id TEXT PRIMARY KEY,
    course_id TEXT NOT NULL,
    topic_id TEXT NOT NULL,
    local_question_number INTEGER NOT NULL CHECK(local_question_number > 0),
    source_id TEXT NOT NULL REFERENCES course_sources(source_id),
    source_ref TEXT NOT NULL,
    answer_source_ref TEXT,
    source_sha256 TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK(question_type IN ('single_choice', 'multiple_choice')),
    prompt TEXT NOT NULL,
    options_json TEXT NOT NULL,
    correct_options_json TEXT NOT NULL DEFAULT '[]',
    answer_validation_status TEXT NOT NULL
        CHECK(answer_validation_status IN ('unverified', 'source_verified', 'disputed')),
    distribution_scope TEXT NOT NULL CHECK(distribution_scope = 'private_only'),
    explanation TEXT,
    explanation_status TEXT NOT NULL DEFAULT 'pending_human_review'
        CHECK(explanation_status IN ('pending_human_review', 'verified')),
    prompt_zh TEXT,
    options_zh_json TEXT,
    translation_status TEXT NOT NULL DEFAULT 'missing'
        CHECK(translation_status IN ('missing', 'draft', 'human_verified')),
    translation_version TEXT,
    translation_reviewed_at TEXT,
    markdown_answer_value TEXT,
    learner_reasoning TEXT,
    content_hash TEXT NOT NULL,
    version TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(source_id, local_question_number)
);

CREATE INDEX IF NOT EXISTS idx_questions_validation
    ON questions(answer_validation_status, distribution_scope);
CREATE INDEX IF NOT EXISTS idx_questions_content_hash ON questions(content_hash);

CREATE TABLE IF NOT EXISTS question_sets (
    question_set_id TEXT NOT NULL,
    version TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    question_ids_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    private_only INTEGER NOT NULL CHECK(private_only = 1),
    PRIMARY KEY(question_set_id, version)
);

CREATE TABLE IF NOT EXISTS game_sessions (
    session_id TEXT PRIMARY KEY,
    question_set_id TEXT NOT NULL,
    question_set_version TEXT NOT NULL,
    ruleset_version TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    duration_ms INTEGER CHECK(duration_ms IS NULL OR duration_ms >= 0),
    correct_count INTEGER NOT NULL DEFAULT 0 CHECK(correct_count >= 0),
    max_streak INTEGER NOT NULL DEFAULT 0 CHECK(max_streak >= 0),
    xp_earned INTEGER NOT NULL DEFAULT 0 CHECK(xp_earned >= 0),
    status TEXT NOT NULL CHECK(status IN ('active', 'completed')),
    completion_event_id TEXT UNIQUE,
    completion_result_json TEXT,
    shuffle_seed TEXT,
    question_order_json TEXT,
    option_orders_json TEXT,
    assistance_mode TEXT NOT NULL DEFAULT 'none'
        CHECK(assistance_mode IN ('none', 'zh_translation')),
    time_multiplier REAL NOT NULL DEFAULT 1.0,
    raw_duration_ms INTEGER CHECK(raw_duration_ms IS NULL OR raw_duration_ms >= 0),
    ranked_duration_ms INTEGER CHECK(ranked_duration_ms IS NULL OR ranked_duration_ms >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(question_set_id, question_set_version)
        REFERENCES question_sets(question_set_id, version)
);

CREATE INDEX IF NOT EXISTS idx_game_sessions_leaderboard
    ON game_sessions(question_set_id, question_set_version, ruleset_version,
                     status, correct_count DESC, duration_ms ASC);

CREATE TABLE IF NOT EXISTS question_attempts (
    attempt_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES game_sessions(session_id),
    question_id TEXT NOT NULL REFERENCES questions(question_id),
    chosen_options_json TEXT NOT NULL,
    correct INTEGER NOT NULL CHECK(correct IN (0, 1)),
    response_ms INTEGER NOT NULL CHECK(response_ms >= 0),
    streak_after INTEGER NOT NULL CHECK(streak_after >= 0),
    xp_earned INTEGER NOT NULL CHECK(xp_earned >= 0),
    attempt_index INTEGER NOT NULL CHECK(attempt_index > 0),
    event_id TEXT NOT NULL UNIQUE,
    result_json TEXT NOT NULL,
    chosen_option_tokens_json TEXT NOT NULL DEFAULT '[]',
    presentation_order_json TEXT NOT NULL DEFAULT '[]',
    assistance_mode TEXT NOT NULL DEFAULT 'none'
        CHECK(assistance_mode IN ('none', 'zh_translation')),
    evidence_mode TEXT NOT NULL DEFAULT 'unassisted'
        CHECK(evidence_mode IN ('unassisted', 'assisted')),
    created_at TEXT NOT NULL,
    UNIQUE(session_id, question_id),
    UNIQUE(session_id, attempt_index)
);

CREATE TABLE IF NOT EXISTS reward_events (
    reward_event_id TEXT PRIMARY KEY,
    session_id TEXT NOT NULL REFERENCES game_sessions(session_id),
    attempt_id TEXT UNIQUE REFERENCES question_attempts(attempt_id),
    event_type TEXT NOT NULL,
    xp_delta INTEGER NOT NULL,
    idempotency_key TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS event_outbox (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    idempotency_key TEXT,
    schema_version INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'processing', 'processed', 'failed')),
    created_at TEXT NOT NULL,
    processed_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS import_runs (
    import_id TEXT PRIMARY KEY,
    course_root TEXT NOT NULL,
    topic_count INTEGER NOT NULL,
    candidate_question_count INTEGER NOT NULL,
    source_verified_count INTEGER NOT NULL,
    duplicate_count INTEGER NOT NULL,
    disputed_count INTEGER NOT NULL,
    failed_count INTEGER NOT NULL,
    selected_question_ids_json TEXT NOT NULL,
    source_paths_json TEXT NOT NULL,
    report_path TEXT NOT NULL,
    started_at TEXT NOT NULL,
    completed_at TEXT NOT NULL
);
"""


def _columns(db: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def _add_column_if_missing(
    db: sqlite3.Connection, table: str, column: str, declaration: str
) -> None:
    if column not in _columns(db, table):
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _upgrade_legacy_tables(db: sqlite3.Connection) -> None:
    """Bring databases made by the v0.1 starter up to the migrated schema."""

    _add_column_if_missing(db, "course_sources", "content_hash", "TEXT NOT NULL DEFAULT ''")
    _add_column_if_missing(
        db, "course_sources", "source_type", "TEXT NOT NULL DEFAULT 'personal_notes'"
    )
    _add_column_if_missing(db, "questions", "answer_source_ref", "TEXT")
    _add_column_if_missing(db, "event_outbox", "idempotency_key", "TEXT")
    _add_column_if_missing(
        db, "event_outbox", "schema_version", "INTEGER NOT NULL DEFAULT 1"
    )
    _add_column_if_missing(
        db, "event_outbox", "status", "TEXT NOT NULL DEFAULT 'pending'"
    )
    _add_column_if_missing(db, "event_outbox", "processed_at", "TEXT")
    _add_column_if_missing(db, "event_outbox", "last_error", "TEXT")
    db.execute("UPDATE event_outbox SET idempotency_key=id WHERE idempotency_key IS NULL")
    db.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_event_outbox_idempotency "
        "ON event_outbox(idempotency_key) WHERE idempotency_key IS NOT NULL"
    )


def _upgrade_game_feel_v2(db: sqlite3.Connection) -> None:
    """Add ruleset-v2 presentation and assistance data without rewriting history."""

    _add_column_if_missing(db, "questions", "prompt_zh", "TEXT")
    _add_column_if_missing(db, "questions", "options_zh_json", "TEXT")
    _add_column_if_missing(
        db, "questions", "translation_status", "TEXT NOT NULL DEFAULT 'missing'"
    )
    _add_column_if_missing(db, "questions", "translation_version", "TEXT")
    _add_column_if_missing(db, "questions", "translation_reviewed_at", "TEXT")

    _add_column_if_missing(db, "game_sessions", "shuffle_seed", "TEXT")
    _add_column_if_missing(db, "game_sessions", "question_order_json", "TEXT")
    _add_column_if_missing(db, "game_sessions", "option_orders_json", "TEXT")
    _add_column_if_missing(
        db, "game_sessions", "assistance_mode", "TEXT NOT NULL DEFAULT 'none'"
    )
    _add_column_if_missing(
        db, "game_sessions", "time_multiplier", "REAL NOT NULL DEFAULT 1.0"
    )
    _add_column_if_missing(db, "game_sessions", "raw_duration_ms", "INTEGER")
    _add_column_if_missing(db, "game_sessions", "ranked_duration_ms", "INTEGER")

    _add_column_if_missing(
        db,
        "question_attempts",
        "chosen_option_tokens_json",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(
        db,
        "question_attempts",
        "presentation_order_json",
        "TEXT NOT NULL DEFAULT '[]'",
    )
    _add_column_if_missing(
        db, "question_attempts", "assistance_mode", "TEXT NOT NULL DEFAULT 'none'"
    )
    _add_column_if_missing(
        db, "question_attempts", "evidence_mode", "TEXT NOT NULL DEFAULT 'unassisted'"
    )

    # v1 sessions remain ruleset v1. These values only make their legacy timing
    # explicit; they are never mixed into a ruleset-v2 Personal Best query.
    db.execute(
        """UPDATE game_sessions SET
               raw_duration_ms=COALESCE(raw_duration_ms,duration_ms),
               ranked_duration_ms=COALESCE(ranked_duration_ms,duration_ms),
               assistance_mode=COALESCE(assistance_mode,'none'),
               time_multiplier=COALESCE(time_multiplier,1.0)"""
    )
    db.execute(
        """CREATE INDEX IF NOT EXISTS idx_game_sessions_ranked_leaderboard
           ON game_sessions(question_set_id,question_set_version,ruleset_version,
                            status,correct_count DESC,ranked_duration_ms ASC)"""
    )


def initialize() -> None:
    with connect() as db:
        db.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                version INTEGER PRIMARY KEY,
                name TEXT NOT NULL,
                applied_at TEXT NOT NULL
            )"""
        )
        applied = {
            row["version"] for row in db.execute("SELECT version FROM schema_migrations")
        }
        if 1 not in applied:
            db.executescript(SCHEMA_V1)
            db.execute(
                "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (1, "game_slice_schema", utc_now_iso()),
            )
        if 2 not in applied:
            _upgrade_legacy_tables(db)
            db.execute(
                "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (2, "upgrade_v01_columns", utc_now_iso()),
            )
        if 3 not in applied:
            _upgrade_game_feel_v2(db)
            db.execute(
                "INSERT INTO schema_migrations(version,name,applied_at) VALUES(?,?,?)",
                (3, "game_feel_ruleset_v2", utc_now_iso()),
            )
