"""Local-only Study Core API for the private Speed Run slice."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
import secrets
import sqlite3
import uuid
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from .database import connect, initialize, utc_now_iso
from .game import (
    GAME_RULESET_VERSION,
    PENDING_EXPLANATION,
    build_session_presentation,
    calculate_ranked_duration,
    option_token,
    personal_best,
    score_is_better,
    time_multiplier_for,
    xp_for_answer,
)
from .importer import FIRST_QUESTION_SET_ID, QUESTION_SET_SIZE


AssistanceMode = Literal["none", "zh_translation"]


def _new_id() -> str:
    return str(uuid.uuid4())


def _new_shuffle_seed() -> str:
    """Server-only entropy source, kept separate so tests can inject a seed."""

    return secrets.token_hex(16)


def _json_list(value: str | None) -> list:
    parsed = json.loads(value or "[]")
    if not isinstance(parsed, list):
        raise ValueError("Expected a JSON list")
    return parsed


def _json_object(value: str | None) -> dict:
    parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object")
    return parsed


def _outbox(
    db: sqlite3.Connection,
    event_type: str,
    payload: dict[str, object],
    idempotency_key: str,
    timestamp: str,
) -> None:
    db.execute(
        """INSERT INTO event_outbox(
            id,type,payload_json,idempotency_key,schema_version,status,created_at)
            VALUES(?,?,?,?,2,'pending',?)""",
        (
            _new_id(),
            event_type,
            json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            idempotency_key,
            timestamp,
        ),
    )


@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize()
    with connect() as db:
        db.execute(
            """INSERT OR IGNORE INTO tasks(id,title,minutes,status,created_at)
               VALUES(?,?,?,?,?)""",
            (
                "cybersecurity-start",
                "打开 Cyber Security，完成一个 10 分钟知识点",
                10,
                "pending",
                utc_now_iso(),
            ),
        )
    yield


app = FastAPI(title="Rae Learning OS / Study Core", version="0.3.1", lifespan=lifespan)


class StartInput(BaseModel):
    question_set_id: str | None = None
    assistance_mode: AssistanceMode = "none"


class AttemptInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    question_id: str = Field(min_length=1, max_length=200)
    chosen_option_tokens: list[str] = Field(min_length=1, max_length=4)
    response_ms: int = Field(ge=0, le=3_600_000)

    @field_validator("chosen_option_tokens")
    @classmethod
    def tokens_are_unique(cls, value: list[str]) -> list[str]:
        if any(not token or len(token) > 128 for token in value):
            raise ValueError("chosen_option_tokens contains an invalid token")
        if len(set(value)) != len(value):
            raise ValueError("chosen_option_tokens must not contain duplicates")
        return sorted(value)


class CompleteInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)


class SessionInput(BaseModel):
    """Legacy non-game study log retained for the isolated Study Bot."""

    task_id: str
    duration_minutes: int = Field(ge=1, le=480)
    evidence_note: str = Field(min_length=5, max_length=2000)
    activity_type: str = Field(default="study", pattern="^(study|demo_game|quiz)$")


def _load_default_set(db: sqlite3.Connection) -> tuple[sqlite3.Row, list[sqlite3.Row]]:
    question_set = db.execute(
        """SELECT * FROM question_sets
           WHERE question_set_id=? AND private_only=1
           ORDER BY created_at DESC, version DESC LIMIT 1""",
        (FIRST_QUESTION_SET_ID,),
    ).fetchone()
    if question_set is None:
        raise HTTPException(
            status_code=409,
            detail="No private verified question set. Run the read-only course import first.",
        )
    if question_set["ruleset_version"] != GAME_RULESET_VERSION:
        raise HTTPException(
            status_code=409,
            detail="The private question set must be re-imported for ruleset v2.",
        )
    question_ids = _json_list(question_set["question_ids_json"])
    if len(question_ids) != QUESTION_SET_SIZE or len(set(question_ids)) != QUESTION_SET_SIZE:
        raise HTTPException(status_code=409, detail="The active question set is invalid")
    placeholders = ",".join("?" for _ in question_ids)
    rows = db.execute(
        f"""SELECT * FROM questions WHERE question_id IN ({placeholders})
            AND answer_validation_status='source_verified'
            AND distribution_scope='private_only'""",
        question_ids,
    ).fetchall()
    by_id = {row["question_id"]: row for row in rows}
    if set(by_id) != set(question_ids):
        raise HTTPException(
            status_code=409,
            detail="Question set contains an unverified or unavailable question",
        )
    return question_set, [by_id[question_id] for question_id in question_ids]


def _translation_ready(questions: list[sqlite3.Row]) -> bool:
    for question in questions:
        if question["translation_status"] != "human_verified" or not question["prompt_zh"]:
            return False
        translations = _json_list(question["options_zh_json"])
        options = _json_list(question["options_json"])
        if len(translations) != len(options) or any(not str(item).strip() for item in translations):
            return False
    return True


def _session_orders(session: sqlite3.Row) -> tuple[list[str], dict[str, list[int]]]:
    question_order = [str(item) for item in _json_list(session["question_order_json"])]
    raw_orders = _json_object(session["option_orders_json"])
    option_orders = {
        str(question_id): [int(item) for item in order]
        for question_id, order in raw_orders.items()
        if isinstance(order, list)
    }
    if not question_order or set(question_order) != set(option_orders):
        raise HTTPException(status_code=409, detail="Stored session presentation is invalid")
    return question_order, option_orders


def _session_questions(db: sqlite3.Connection, session: sqlite3.Row) -> list[dict[str, object]]:
    question_order, option_orders = _session_orders(session)
    placeholders = ",".join("?" for _ in question_order)
    rows = db.execute(
        f"SELECT * FROM questions WHERE question_id IN ({placeholders})", question_order
    ).fetchall()
    by_id = {row["question_id"]: row for row in rows}
    assisted = session["assistance_mode"] == "zh_translation"
    payload: list[dict[str, object]] = []
    for question_id in question_order:
        question = by_id.get(question_id)
        if question is None:
            raise HTTPException(status_code=409, detail="A session question is unavailable")
        options = _json_list(question["options_json"])
        option_order = option_orders[question_id]
        if sorted(option_order) != list(range(1, len(options) + 1)):
            raise HTTPException(status_code=409, detail="Stored option presentation is invalid")
        translated_options = _json_list(question["options_zh_json"]) if assisted else []
        if assisted and (
            question["translation_status"] != "human_verified"
            or not question["prompt_zh"]
            or len(translated_options) != len(options)
        ):
            raise HTTPException(status_code=409, detail="Verified Chinese translation is unavailable")
        presented_options = []
        for canonical in option_order:
            item: dict[str, object] = {
                "option_token": option_token(session["shuffle_seed"], question_id, canonical),
                "text": options[canonical - 1],
            }
            if assisted:
                item["text_zh"] = translated_options[canonical - 1]
            presented_options.append(item)
        item = {
            "question_id": question_id,
            "question_type": question["question_type"],
            "prompt": question["prompt"],
            "options": presented_options,
        }
        if assisted:
            item["prompt_zh"] = question["prompt_zh"]
            item["translation_version"] = question["translation_version"]
        payload.append(item)
    return payload


def _elapsed_raw_ms(session: sqlite3.Row) -> int:
    if session["raw_duration_ms"] is not None:
        return int(session["raw_duration_ms"])
    started_at = datetime.fromisoformat(session["started_at"])
    return max(0, int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000))


def _pb_payload(row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    raw = row["raw_duration_ms"] if row["raw_duration_ms"] is not None else row["duration_ms"]
    ranked = (
        row["ranked_duration_ms"]
        if row["ranked_duration_ms"] is not None
        else row["duration_ms"]
    )
    return {
        "session_id": row["session_id"],
        "question_set_id": row["question_set_id"],
        "question_set_version": row["question_set_version"],
        "ruleset_version": row["ruleset_version"],
        "question_count": QUESTION_SET_SIZE,
        "correct_count": row["correct_count"],
        "duration_ms": raw,
        "raw_duration_ms": raw,
        "ranked_duration_ms": ranked,
        "assistance_mode": row["assistance_mode"],
        "time_multiplier": row["time_multiplier"],
        "max_streak": row["max_streak"],
        "xp_earned": row["xp_earned"],
        "completed_at": row["completed_at"],
    }


@app.get("/health")
def health() -> dict[str, object]:
    initialize()
    with connect() as db:
        db.execute("SELECT 1").fetchone()
    return {"ok": True, "service": "study-core", "api_version": "v1"}


@app.get("/api/v1/game-config")
def game_config() -> dict[str, object]:
    initialize()
    with connect() as db:
        question_set, questions = _load_default_set(db)
        zh_ready = _translation_ready(questions)
    return {
        "question_set_id": question_set["question_set_id"],
        "question_set_version": question_set["version"],
        "ruleset_version": GAME_RULESET_VERSION,
        "question_count": len(questions),
        "assistance": {
            "zh_translation_available": zh_ready,
            "zh_translation_status": "human_verified" if zh_ready else "pending_review",
            "time_multiplier": 1.3,
        },
    }


@app.post("/api/v1/game-sessions/start", status_code=201)
def start_game(body: StartInput | None = None) -> dict[str, object]:
    initialize()
    request = body or StartInput()
    with connect() as db:
        question_set, questions = _load_default_set(db)
        if request.question_set_id not in (None, question_set["question_set_id"]):
            raise HTTPException(status_code=400, detail="Only the fixed private set is available")
        if request.assistance_mode == "zh_translation" and not _translation_ready(questions):
            raise HTTPException(
                status_code=409,
                detail="中文辅助待人工复核：本题组尚无完整的 human_verified 翻译。",
            )
        shuffle_seed = _new_shuffle_seed()
        canonical_ids = [row["question_id"] for row in questions]
        question_order, option_orders = build_session_presentation(
            canonical_ids, shuffle_seed
        )
        session_id = _new_id()
        timestamp = utc_now_iso()
        multiplier = time_multiplier_for(request.assistance_mode)
        db.execute(
            """INSERT INTO game_sessions(
                session_id,question_set_id,question_set_version,ruleset_version,
                started_at,status,shuffle_seed,question_order_json,option_orders_json,
                assistance_mode,time_multiplier,created_at,updated_at)
                VALUES(?,?,?,?,?,'active',?,?,?,?,?,?,?)""",
            (
                session_id,
                question_set["question_set_id"],
                question_set["version"],
                GAME_RULESET_VERSION,
                timestamp,
                shuffle_seed,
                json.dumps(question_order, separators=(",", ":")),
                json.dumps(option_orders, separators=(",", ":")),
                request.assistance_mode,
                multiplier,
                timestamp,
                timestamp,
            ),
        )
        session = db.execute(
            "SELECT * FROM game_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        presented_questions = _session_questions(db, session)
        _outbox(
            db,
            "game.session.started",
            {
                "session_id": session_id,
                "question_set_version": question_set["version"],
                "ruleset_version": GAME_RULESET_VERSION,
                "assistance_mode": request.assistance_mode,
            },
            f"game.session.started:{session_id}",
            timestamp,
        )
    return {
        "session_id": session_id,
        "question_set_id": question_set["question_set_id"],
        "question_set_version": question_set["version"],
        "ruleset_version": GAME_RULESET_VERSION,
        "started_at": timestamp,
        "assistance_mode": request.assistance_mode,
        "time_multiplier": multiplier,
        "question_count": len(presented_questions),
        "question_order": question_order,
        "questions": presented_questions,
    }


def _stored_attempt_or_conflict(
    db: sqlite3.Connection, session_id: str, body: AttemptInput
) -> dict[str, object] | None:
    existing = db.execute(
        "SELECT * FROM question_attempts WHERE event_id=?", (body.event_id,)
    ).fetchone()
    if existing is None:
        return None
    if (
        existing["session_id"] != session_id
        or existing["question_id"] != body.question_id
        or sorted(_json_list(existing["chosen_option_tokens_json"]))
        != body.chosen_option_tokens
        or existing["response_ms"] != body.response_ms
    ):
        raise HTTPException(status_code=409, detail="event_id was already used for another attempt")
    return json.loads(existing["result_json"])


@app.post("/api/v1/game-sessions/{session_id}/attempts", status_code=201)
def submit_attempt(session_id: str, body: AttemptInput) -> dict[str, object]:
    initialize()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        replay = _stored_attempt_or_conflict(db, session_id, body)
        if replay is not None:
            return replay
        session = db.execute(
            "SELECT * FROM game_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown game session")
        if session["status"] != "active":
            raise HTTPException(status_code=409, detail="Game session is already completed")
        question_order, option_orders = _session_orders(session)
        attempted_count = db.execute(
            "SELECT COUNT(*) FROM question_attempts WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        if attempted_count >= len(question_order):
            raise HTTPException(status_code=409, detail="All questions were already answered")
        expected_question_id = question_order[attempted_count]
        if body.question_id != expected_question_id:
            raise HTTPException(status_code=409, detail="Questions must follow session order")
        question = db.execute(
            """SELECT * FROM questions WHERE question_id=?
               AND answer_validation_status='source_verified'
               AND distribution_scope='private_only'""",
            (body.question_id,),
        ).fetchone()
        if question is None:
            raise HTTPException(status_code=409, detail="Question is not eligible for play")
        options = _json_list(question["options_json"])
        token_to_canonical = {
            option_token(session["shuffle_seed"], body.question_id, canonical): canonical
            for canonical in option_orders[body.question_id]
        }
        if any(token not in token_to_canonical for token in body.chosen_option_tokens):
            raise HTTPException(status_code=422, detail="Chosen option token is invalid")
        if question["question_type"] == "single_choice" and len(body.chosen_option_tokens) != 1:
            raise HTTPException(status_code=422, detail="This question requires one option")
        chosen_canonical = sorted(
            token_to_canonical[token] for token in body.chosen_option_tokens
        )
        correct_canonical = sorted(_json_list(question["correct_options_json"]))
        correct = chosen_canonical == correct_canonical
        previous = db.execute(
            """SELECT streak_after FROM question_attempts
               WHERE session_id=? ORDER BY attempt_index DESC LIMIT 1""",
            (session_id,),
        ).fetchone()
        previous_streak = previous["streak_after"] if previous else 0
        streak_after = previous_streak + 1 if correct else 0
        xp = xp_for_answer(correct, streak_after)
        attempt_index = attempted_count + 1
        attempt_id = _new_id()
        timestamp = utc_now_iso()
        total_xp = session["xp_earned"] + xp
        correct_count = session["correct_count"] + int(correct)
        max_streak = max(session["max_streak"], streak_after)
        correct_tokens = [
            option_token(session["shuffle_seed"], body.question_id, canonical)
            for canonical in correct_canonical
        ]
        presentation_tokens = [
            option_token(session["shuffle_seed"], body.question_id, canonical)
            for canonical in option_orders[body.question_id]
        ]
        result: dict[str, object] = {
            "attempt_id": attempt_id,
            "event_id": body.event_id,
            "question_id": body.question_id,
            "correct": correct,
            "correct_option_tokens": correct_tokens,
            "source_ref": question["source_ref"],
            "explanation": (
                question["explanation"]
                if question["explanation_status"] == "verified" and question["explanation"]
                else PENDING_EXPLANATION
            ),
            "explanation_status": question["explanation_status"],
            "assistance_mode": session["assistance_mode"],
            "evidence_mode": (
                "assisted"
                if session["assistance_mode"] == "zh_translation"
                else "unassisted"
            ),
            "streak": streak_after,
            "xp_earned": xp,
            "total_xp": total_xp,
            "correct_count": correct_count,
            "attempted_count": attempt_index,
            "remaining_count": len(question_order) - attempt_index,
            "saved": True,
        }
        db.execute(
            """INSERT INTO question_attempts(
                attempt_id,session_id,question_id,chosen_options_json,correct,
                response_ms,streak_after,xp_earned,attempt_index,event_id,
                result_json,chosen_option_tokens_json,presentation_order_json,
                assistance_mode,evidence_mode,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                attempt_id,
                session_id,
                body.question_id,
                json.dumps(chosen_canonical),
                int(correct),
                body.response_ms,
                streak_after,
                xp,
                attempt_index,
                body.event_id,
                json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                json.dumps(body.chosen_option_tokens),
                json.dumps(presentation_tokens),
                session["assistance_mode"],
                "assisted" if session["assistance_mode"] == "zh_translation" else "unassisted",
                timestamp,
            ),
        )
        db.execute(
            """UPDATE game_sessions SET correct_count=?,max_streak=?,xp_earned=?,updated_at=?
               WHERE session_id=?""",
            (correct_count, max_streak, total_xp, timestamp, session_id),
        )
        db.execute(
            """INSERT INTO reward_events(
                reward_event_id,session_id,attempt_id,event_type,xp_delta,
                idempotency_key,created_at)
                VALUES(?,?,?,'question_attempt',?,?,?)""",
            (_new_id(), session_id, attempt_id, xp, f"reward:{body.event_id}", timestamp),
        )
        _outbox(
            db,
            "answer.submitted",
            {
                "session_id": session_id,
                "attempt_id": attempt_id,
                "question_id": body.question_id,
                "correct": correct,
                "xp_earned": xp,
                "evidence_mode": result["evidence_mode"],
            },
            f"answer.submitted:{body.event_id}",
            timestamp,
        )
    return result


@app.post("/api/v1/game-sessions/{session_id}/complete")
def complete_game(session_id: str, body: CompleteInput) -> dict[str, object]:
    initialize()
    with connect() as db:
        db.execute("BEGIN IMMEDIATE")
        event_owner = db.execute(
            "SELECT session_id FROM game_sessions WHERE completion_event_id=?",
            (body.event_id,),
        ).fetchone()
        if event_owner is not None and event_owner["session_id"] != session_id:
            raise HTTPException(status_code=409, detail="event_id was used for another completion")
        session = db.execute(
            "SELECT * FROM game_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown game session")
        if session["status"] == "completed":
            if session["completion_event_id"] == body.event_id:
                return json.loads(session["completion_result_json"])
            raise HTTPException(status_code=409, detail="Game session is already completed")
        question_order, _option_orders = _session_orders(session)
        attempt_count = db.execute(
            "SELECT COUNT(*) FROM question_attempts WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        if attempt_count != len(question_order):
            raise HTTPException(status_code=409, detail="Answer every question before completion")
        completed_at = datetime.now(timezone.utc)
        started_at = datetime.fromisoformat(session["started_at"])
        raw_duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
        ranked_duration_ms = calculate_ranked_duration(
            raw_duration_ms, session["assistance_mode"]
        )
        old_best = personal_best(
            db,
            session["question_set_id"],
            session["question_set_version"],
            session["ruleset_version"],
            exclude_session_id=session_id,
        )
        old_ranked = (
            old_best["ranked_duration_ms"]
            if old_best is not None and old_best["ranked_duration_ms"] is not None
            else old_best["duration_ms"] if old_best is not None else None
        )
        is_personal_best = old_best is None or score_is_better(
            session["correct_count"],
            ranked_duration_ms,
            old_best["correct_count"],
            int(old_ranked),
        )
        result: dict[str, object] = {
            "session_id": session_id,
            "question_set_id": session["question_set_id"],
            "question_set_version": session["question_set_version"],
            "ruleset_version": session["ruleset_version"],
            "completed_at": completed_at.isoformat(),
            "duration_ms": raw_duration_ms,
            "raw_duration_ms": raw_duration_ms,
            "assistance_mode": session["assistance_mode"],
            "time_multiplier": session["time_multiplier"],
            "ranked_duration_ms": ranked_duration_ms,
            "question_count": len(question_order),
            "correct_count": session["correct_count"],
            "max_streak": session["max_streak"],
            "xp_earned": session["xp_earned"],
            "is_personal_best": is_personal_best,
            "saved": True,
        }
        result_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        db.execute(
            """UPDATE game_sessions SET
                status='completed',completed_at=?,duration_ms=?,raw_duration_ms=?,
                ranked_duration_ms=?,completion_event_id=?,completion_result_json=?,updated_at=?
                WHERE session_id=?""",
            (
                completed_at.isoformat(),
                raw_duration_ms,
                raw_duration_ms,
                ranked_duration_ms,
                body.event_id,
                result_json,
                completed_at.isoformat(),
                session_id,
            ),
        )
        _outbox(
            db,
            "game.session.completed",
            {
                "session_id": session_id,
                "correct_count": session["correct_count"],
                "raw_duration_ms": raw_duration_ms,
                "ranked_duration_ms": ranked_duration_ms,
                "assistance_mode": session["assistance_mode"],
                "xp_earned": session["xp_earned"],
            },
            f"game.session.completed:{body.event_id}",
            completed_at.isoformat(),
        )
    return result


@app.get("/api/v1/game-sessions/{session_id}/result")
def game_result(session_id: str) -> dict[str, object]:
    initialize()
    with connect() as db:
        session = db.execute(
            "SELECT * FROM game_sessions WHERE session_id=?", (session_id,)
        ).fetchone()
        if session is None:
            raise HTTPException(status_code=404, detail="Unknown game session")
        attempts = db.execute(
            """SELECT result_json FROM question_attempts
               WHERE session_id=? ORDER BY attempt_index""",
            (session_id,),
        ).fetchall()
        best = personal_best(
            db,
            session["question_set_id"],
            session["question_set_version"],
            session["ruleset_version"],
        )
        raw_elapsed = _elapsed_raw_ms(session)
        ranked_elapsed = (
            int(session["ranked_duration_ms"])
            if session["ranked_duration_ms"] is not None
            else calculate_ranked_duration(raw_elapsed, session["assistance_mode"])
        )
        if session["completion_result_json"]:
            result = json.loads(session["completion_result_json"])
        else:
            result = {
                "session_id": session_id,
                "question_set_id": session["question_set_id"],
                "question_set_version": session["question_set_version"],
                "ruleset_version": session["ruleset_version"],
                "correct_count": session["correct_count"],
                "max_streak": session["max_streak"],
                "xp_earned": session["xp_earned"],
            }
        question_order, _option_orders = _session_orders(session)
        result.update(
            {
                "status": session["status"],
                "started_at": session["started_at"],
                "question_count": len(question_order),
                "question_order": question_order,
                "questions": _session_questions(db, session),
                "assistance_mode": session["assistance_mode"],
                "time_multiplier": session["time_multiplier"],
                "raw_duration_ms": raw_elapsed,
                "ranked_duration_ms": ranked_elapsed,
                "attempts": [json.loads(row["result_json"]) for row in attempts],
                "is_current_personal_best": bool(
                    best is not None and best["session_id"] == session_id
                ),
            }
        )
    return result


@app.get("/api/v1/dashboard")
def dashboard() -> dict[str, object]:
    initialize()
    with connect() as db:
        latest_import = db.execute(
            "SELECT * FROM import_runs ORDER BY completed_at DESC LIMIT 1"
        ).fetchone()
        recent = db.execute(
            """SELECT * FROM game_sessions WHERE status='completed'
               ORDER BY completed_at DESC LIMIT 1"""
        ).fetchone()
        best = (
            personal_best(
                db,
                recent["question_set_id"],
                recent["question_set_version"],
                recent["ruleset_version"],
            )
            if recent is not None
            else None
        )
        updated_values = [
            value
            for value in (
                latest_import["completed_at"] if latest_import else None,
                recent["updated_at"] if recent else None,
            )
            if value
        ]
    return {
        "timezone": "Europe/Helsinki",
        "import_stats": {
            "topic_count": latest_import["topic_count"] if latest_import else 0,
            "candidate_question_count": (
                latest_import["candidate_question_count"] if latest_import else 0
            ),
            "source_verified_count": (
                latest_import["source_verified_count"] if latest_import else 0
            ),
        },
        "recent_game": _pb_payload(recent),
        "personal_best": _pb_payload(best),
        "last_imported_at": latest_import["completed_at"] if latest_import else None,
        "last_updated_at": max(updated_values) if updated_values else None,
        "official_grade": None,
        "official_grade_status": "pending_confirmation",
        "mastery": "unknown",
        "mastery_label": "尚未测评",
        "xp_is_official_grade": False,
    }


@app.get("/api/v1/tasks")
def tasks() -> dict[str, object]:
    with connect() as db:
        rows = db.execute(
            "SELECT id,title,minutes,status,completed_at FROM tasks ORDER BY status,id"
        ).fetchall()
    return {"items": [dict(row) for row in rows]}


@app.get("/api/v1/summary")
def legacy_summary() -> dict[str, object]:
    """Compatibility view; academic fields remain explicitly unknown."""

    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        done = db.execute("SELECT COUNT(*) FROM tasks WHERE status='completed'").fetchone()[0]
        sources = db.execute("SELECT COUNT(*) FROM course_sources").fetchone()[0]
    return {
        "timezone": "Europe/Helsinki",
        "last_updated_at": utc_now_iso(),
        "task_total": total,
        "task_completed": done,
        "imported_source_count": sources,
        "official_grade": None,
        "estimated_grade": None,
        "mastery": "unknown",
        "exam_deadline": None,
    }


@app.post("/api/v1/sessions", status_code=201)
def create_study_session(body: SessionInput) -> dict[str, object]:
    session_id = _new_id()
    event_id = _new_id()
    timestamp = utc_now_iso()
    with connect() as db:
        task = db.execute("SELECT status FROM tasks WHERE id=?", (body.task_id,)).fetchone()
        if task is None:
            raise HTTPException(status_code=404, detail="Unknown task")
        db.execute(
            """INSERT INTO study_sessions
                (id,task_id,duration_minutes,evidence_note,activity_type,created_at)
                VALUES(?,?,?,?,?,?)""",
            (
                session_id,
                body.task_id,
                body.duration_minutes,
                body.evidence_note,
                body.activity_type,
                timestamp,
            ),
        )
        _outbox(
            db,
            "study.session_recorded",
            {
                "session_id": session_id,
                "task_id": body.task_id,
                "activity_type": body.activity_type,
            },
            f"study.session_recorded:{event_id}",
            timestamp,
        )
        if body.activity_type != "demo_game":
            db.execute(
                """UPDATE tasks SET status='completed',completed_at=?
                   WHERE id=? AND status='pending'""",
                (timestamp, body.task_id),
            )
    return {
        "session_id": session_id,
        "event_id": event_id,
        "task_marked_completed": body.activity_type != "demo_game",
    }


def run() -> None:
    host = os.getenv("LEARNING_OS_HOST", "127.0.0.1")
    if host != "127.0.0.1":
        raise RuntimeError("Study Core may only bind to 127.0.0.1")
    port = int(os.getenv("LEARNING_OS_PORT", "8876"))
    import uvicorn

    uvicorn.run("app.main:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    run()
