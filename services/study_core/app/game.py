"""Deterministic ruleset-v2 game rules shared by the API and tests."""

from __future__ import annotations

from hashlib import sha256
import random
import sqlite3


GAME_RULESET_VERSION = "2"
PENDING_EXPLANATION = "详细解析待人工复核"
ASSISTANCE_MODES = ("none", "zh_translation")


def xp_for_answer(correct: bool, streak_after: int) -> int:
    """Award bounded game XP; this value is never an academic score."""

    if not correct:
        return 0
    return 10 + min(max(streak_after - 1, 0), 4) * 2


def time_multiplier_for(assistance_mode: str) -> float:
    if assistance_mode == "none":
        return 1.0
    if assistance_mode == "zh_translation":
        return 1.3
    raise ValueError(f"Unsupported assistance mode: {assistance_mode}")


def calculate_ranked_duration(raw_duration_ms: int, assistance_mode: str) -> int:
    """Apply the v2 multiplier with deterministic half-up integer rounding."""

    if raw_duration_ms < 0:
        raise ValueError("raw_duration_ms must be non-negative")
    if assistance_mode == "none":
        return raw_duration_ms
    if assistance_mode == "zh_translation":
        return (raw_duration_ms * 13 + 5) // 10
    raise ValueError(f"Unsupported assistance mode: {assistance_mode}")


def option_token(shuffle_seed: str, question_id: str, canonical_option: int) -> str:
    """Return an opaque stable token; its text does not expose the canonical index."""

    digest = sha256(
        f"{shuffle_seed}\0{question_id}\0{canonical_option}".encode("utf-8")
    ).hexdigest()[:24]
    return f"opt_{digest}"


def build_session_presentation(
    question_ids: list[str], shuffle_seed: str, option_count: int = 4
) -> tuple[list[str], dict[str, list[int]]]:
    """Produce stable question and canonical-option orders for an injected seed."""

    if len(set(question_ids)) != len(question_ids):
        raise ValueError("question_ids must be unique")
    if option_count < 2:
        raise ValueError("option_count must be at least two")
    rng = random.Random(shuffle_seed)
    question_order = list(question_ids)
    rng.shuffle(question_order)
    option_orders: dict[str, list[int]] = {}
    for question_id in question_order:
        order = list(range(1, option_count + 1))
        rng.shuffle(order)
        option_orders[question_id] = order
    return question_order, option_orders


def score_is_better(
    correct_count: int,
    ranked_duration_ms: int,
    other_correct_count: int,
    other_ranked_duration_ms: int,
) -> bool:
    """Correctness dominates ranked speed. Equal scores do not refresh a record."""

    return (correct_count, -ranked_duration_ms) > (
        other_correct_count,
        -other_ranked_duration_ms,
    )


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
        + " ORDER BY correct_count DESC, "
        + "COALESCE(ranked_duration_ms,duration_ms) ASC, completed_at ASC LIMIT 1",
        params,
    ).fetchone()

