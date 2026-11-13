from __future__ import annotations

import sqlite3

from app.database import connect, initialize


def test_ruleset_v2_migration_preserves_v1_session(tmp_path, monkeypatch):
    path = tmp_path / "legacy.sqlite"
    monkeypatch.setenv("LEARNING_OS_DB", str(path))
    db = sqlite3.connect(path)
    db.executescript(
        """
        CREATE TABLE schema_migrations(
            version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL);
        INSERT INTO schema_migrations VALUES(1,'game_slice_schema','2026-01-01T00:00:00+00:00');
        INSERT INTO schema_migrations VALUES(2,'upgrade_v01_columns','2026-01-01T00:00:00+00:00');
        CREATE TABLE questions(question_id TEXT PRIMARY KEY);
        CREATE TABLE question_attempts(attempt_id TEXT PRIMARY KEY);
        CREATE TABLE game_sessions(
            session_id TEXT PRIMARY KEY,
            question_set_id TEXT NOT NULL,
            question_set_version TEXT NOT NULL,
            ruleset_version TEXT NOT NULL,
            status TEXT NOT NULL,
            correct_count INTEGER NOT NULL,
            duration_ms INTEGER
        );
        INSERT INTO game_sessions VALUES(
            'legacy-v1','set','version','1','completed',10,12345);
        """
    )
    db.commit()
    db.close()

    initialize()
    with connect() as migrated:
        row = migrated.execute(
            """SELECT ruleset_version,duration_ms,raw_duration_ms,ranked_duration_ms,
                      assistance_mode,time_multiplier
               FROM game_sessions WHERE session_id='legacy-v1'"""
        ).fetchone()
        versions = [
            item[0]
            for item in migrated.execute("SELECT version FROM schema_migrations ORDER BY version")
        ]
        question_columns = {
            item[1] for item in migrated.execute("PRAGMA table_info(questions)")
        }
    assert tuple(row) == ("1", 12345, 12345, 12345, "none", 1.0)
    assert versions == [1, 2, 3]
    assert {"prompt_zh", "options_zh_json", "translation_status"} <= question_columns
