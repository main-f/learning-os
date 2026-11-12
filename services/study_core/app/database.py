"""Small study-only SQLite store. Never shares a DB with the lifestyle bot."""
import os
import sqlite3
from pathlib import Path


def get_db_path() -> Path:
    return Path(os.getenv("LEARNING_OS_DB", "data/learning.sqlite")).expanduser().resolve()


def connect() -> sqlite3.Connection:
    path = get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    db.execute("PRAGMA journal_mode=WAL")
    return db


def initialize() -> None:
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS tasks (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            minutes INTEGER NOT NULL CHECK(minutes>0),
            status TEXT NOT NULL DEFAULT 'pending'
                 CHECK(status IN ('pending','completed')),
            created_at TEXT NOT NULL,
            completed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS study_sessions (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL REFERENCES tasks(id),
            duration_minutes INTEGER NOT NULL CHECK(duration_minutes>=0),
            evidence_note TEXT NOT NULL,
            activity_type TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS course_sources (
            source_id TEXT PRIMARY KEY,
            relative_path TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            sha256 TEXT NOT NULL,
            imported_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS event_outbox (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            payload_json TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """)
