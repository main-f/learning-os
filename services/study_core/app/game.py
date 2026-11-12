"""Deterministic game rules shared by the API and tests."""

from __future__ import annotations

import sqlite3


PENDING_EXPLANATION = "详细解析待人工复核"


def xp_for_answer(correct: bool, streak_after: int) -> int:
    """Award bounded game XP; this value is never an academic score."""

    if not correct:
        return 0
    return 10 + min(max(streak_after - 1, 0), 4) * 2


def score_is_better(
    correct_count: int,
    duration_ms: int,
    other_correct_count: int,
    other_duration_ms: int,
) -> bool:
    """Correctness dominates speed. Equal scores do not refresh a record."""

    return (correct_count, -duration_ms) > (other_correct_count, -other_duration_ms)


def personal_best(
    db: sqlite3.Connection,
    question_set_id: str,
    question_set_version: str,
    ruleset_version: str,
    exclude_session_id: str | None = None,
) -> sqlite3.Row | None:
    params: list[object] = [question_set_id, question_set_version, ruleset_version]
    exclusion = ""
    if exclude_session_id is not None:
        exclusion = " AND session_id != ?"
        params.append(exclude_session_id)
    return db.execute(
        """SELECT * FROM game_sessions
           WHERE question_set_id=? AND question_set_version=?
             AND ruleset_version=? AND status='completed'"""
        + exclusion
        + " ORDER BY correct_count DESC, duration_ms ASC, completed_at ASC LIMIT 1",
        params,
    ).fetchone()

