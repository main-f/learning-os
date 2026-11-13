"""Fail closed if a public web build contains private study data."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3


PRIVATE_SUFFIXES = {".sqlite", ".sqlite3", ".db", ".m4a", ".mp3"}
SECRET_MARKERS = (
    "STUDY_TELEGRAM_BOT_TOKEN",
    "STUDY_TELEGRAM_ALLOWED_CHAT_ID",
    "LEARNING_OS_DB=",
    "COURSE_ROOT=",
    "BEGIN PRIVATE KEY",
)


def audit_public_build(dist: Path, database: Path | None = None) -> dict[str, int]:
    dist = dist.resolve()
    if not dist.is_dir():
        raise ValueError(f"Build directory does not exist: {dist}")
    files = [path for path in dist.rglob("*") if path.is_file()]
    violations: list[str] = []
    text_payloads: list[tuple[Path, str]] = []
    for path in files:
        if path.suffix.lower() in PRIVATE_SUFFIXES:
            violations.append(f"private file type: {path.relative_to(dist)}")
        raw = path.read_bytes()
        if raw.startswith(b"SQLite format 3"):
            violations.append(f"SQLite payload: {path.relative_to(dist)}")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            continue
        text_payloads.append((path, text))
        for marker in SECRET_MARKERS:
            if marker in text:
                violations.append(f"secret/config marker in {path.relative_to(dist)}")

    checked_questions = 0
    if database is not None and database.is_file():
        db = sqlite3.connect(database)
        try:
            rows = db.execute(
                """SELECT question_id,prompt,options_json,prompt_zh,options_zh_json
                   FROM questions"""
            ).fetchall()
        finally:
            db.close()
        checked_questions = len(rows)
        for question_id, prompt, options_json, prompt_zh, options_zh_json in rows:
            # Single-character/count options cannot be distinguished from ordinary
            # bundle syntax. Prompts remain strict; option thresholds still catch
            # meaningful copied course text without false positives such as "1".
            private_strings = [prompt]
            try:
                private_strings.extend(
                    item for item in json.loads(options_json or "[]") if len(item) >= 20
                )
                private_strings.extend(
                    item for item in json.loads(options_zh_json or "[]") if len(item) >= 6
                )
            except (json.JSONDecodeError, TypeError):
                violations.append(f"invalid private question data: {question_id}")
            if prompt_zh:
                private_strings.append(prompt_zh)
            for private_text in private_strings:
                if not isinstance(private_text, str) or not private_text:
                    continue
                for path, text in text_payloads:
                    if private_text in text:
                        violations.append(
                            f"private question {question_id} in {path.relative_to(dist)}"
                        )
    if violations:
        raise ValueError("Public build audit failed: " + "; ".join(sorted(set(violations))))
    return {"files_checked": len(files), "private_questions_checked": checked_questions}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--database", type=Path)
    args = parser.parse_args()
    result = audit_public_build(args.dist, args.database)
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

