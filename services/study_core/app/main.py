"""Local-only Study Core API for the first real Speed Run slice."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import os
import sqlite3
import uuid

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, field_validator

from .database import connect, initialize, utc_now_iso
from .game import PENDING_EXPLANATION, personal_best, score_is_better, xp_for_answer
from .importer import FIRST_QUESTION_SET_ID, QUESTION_SET_SIZE


def _new_id() -> str:
    return str(uuid.uuid4())


def _json_list(value: str) -> list:
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("Expected a JSON list")
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
            VALUES(?,?,?,?,1,'pending',?)""",
        (
            _new_id(),
            event_type,
            json.dumps(payload, separators=(",", ":")),
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


app = FastAPI(title="Rae Learning OS / Study Core", version="0.3.0", lifespan=lifespan)


class StartInput(BaseModel):
    question_set_id: str | None = None


class AttemptInput(BaseModel):
    event_id: str = Field(min_length=1, max_length=128)
    question_id: str = Field(min_length=1, max_length=200)
    chosen_options: list[int] = Field(min_length=1, max_length=4)
    response_ms: int = Field(ge=0, le=3_600_000)

    @field_validator("chosen_options")
    @classmethod
    def options_are_unique(cls, value: list[int]) -> list[int]:
        if len(set(value)) != len(value):
            raise ValueError("chosen_options must not contain duplicates")
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


def _pb_payload(row: sqlite3.Row | None) -> dict[str, object] | None:
    if row is None:
        return None
    return {
        "session_id": row["session_id"],
        "question_set_id": row["question_set_id"],
        "question_set_version": row["question_set_version"],
        "ruleset_version": row["ruleset_version"],
        "correct_count": row["correct_count"],
        "duration_ms": row["duration_ms"],
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


@app.post("/api/v1/game-sessions/start", status_code=201)
def start_game(body: StartInput | None = None) -> dict[str, object]:
    initialize()
    with connect() as db:
        question_set, questions = _load_default_set(db)
        if body and body.question_set_id not in (None, question_set["question_set_id"]):
            raise HTTPException(status_code=400, detail="Only the fixed private set is available")
        session_id = _new_id()
        timestamp = utc_now_iso()
        db.execute(
            """INSERT INTO game_sessions(
                session_id,question_set_id,question_set_version,ruleset_version,
                started_at,status,created_at,updated_at)
                VALUES(?,?,?,?,?,'active',?,?)""",
            (
                session_id,
                question_set["question_set_id"],
                question_set["version"],
                question_set["ruleset_version"],
                timestamp,
                timestamp,
                timestamp,
            ),
        )
        _outbox(
            db,
            "game.session.started",
            {"session_id": session_id, "question_set_version": question_set["version"]},
            f"game.session.started:{session_id}",
            timestamp,
        )
    return {
        "session_id": session_id,
        "question_set_id": question_set["question_set_id"],
        "question_set_version": question_set["version"],
        "ruleset_version": question_set["ruleset_version"],
        "started_at": timestamp,
        "question_count": len(questions),
        "questions": [
            {
                "question_id": question["question_id"],
                "question_type": question["question_type"],
                "prompt": question["prompt"],
                "options": _json_list(question["options_json"]),
            }
            for question in questions
        ],
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
        or _json_list(existing["chosen_options_json"]) != body.chosen_options
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
        question_set = db.execute(
            """SELECT * FROM question_sets
               WHERE question_set_id=? AND version=?""",
            (session["question_set_id"], session["question_set_version"]),
        ).fetchone()
        if question_set is None:
            raise HTTPException(status_code=409, detail="Question set is unavailable")
        question_ids = _json_list(question_set["question_ids_json"])
        attempted_count = db.execute(
            "SELECT COUNT(*) FROM question_attempts WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        if attempted_count >= len(question_ids):
            raise HTTPException(status_code=409, detail="All questions were already answered")
        expected_question_id = question_ids[attempted_count]
        if body.question_id != expected_question_id:
            raise HTTPException(status_code=409, detail="Questions must be answered in set order")
        question = db.execute(
            """SELECT * FROM questions WHERE question_id=?
               AND answer_validation_status='source_verified'
               AND distribution_scope='private_only'""",
            (body.question_id,),
        ).fetchone()
        if question is None:
            raise HTTPException(status_code=409, detail="Question is not eligible for play")
        options = _json_list(question["options_json"])
        if any(option < 1 or option > len(options) for option in body.chosen_options):
            raise HTTPException(status_code=422, detail="Chosen option is outside the option range")
        if question["question_type"] == "single_choice" and len(body.chosen_options) != 1:
            raise HTTPException(status_code=422, detail="This question requires one option")
        correct_options = _json_list(question["correct_options_json"])
        correct = body.chosen_options == sorted(correct_options)
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
        result: dict[str, object] = {
            "attempt_id": attempt_id,
            "event_id": body.event_id,
            "question_id": body.question_id,
            "correct": correct,
            "correct_options": correct_options,
            "source_ref": question["source_ref"],
            "explanation": (
                question["explanation"]
                if question["explanation_status"] == "verified" and question["explanation"]
                else PENDING_EXPLANATION
            ),
            "explanation_status": question["explanation_status"],
            "streak": streak_after,
            "xp_earned": xp,
            "total_xp": total_xp,
            "correct_count": correct_count,
            "attempted_count": attempt_index,
            "remaining_count": len(question_ids) - attempt_index,
            "saved": True,
        }
        db.execute(
            """INSERT INTO question_attempts(
                attempt_id,session_id,question_id,chosen_options_json,correct,
                response_ms,streak_after,xp_earned,attempt_index,event_id,
                result_json,created_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                attempt_id,
                session_id,
                body.question_id,
                json.dumps(body.chosen_options),
                int(correct),
                body.response_ms,
                streak_after,
                xp,
                attempt_index,
                body.event_id,
                json.dumps(result, ensure_ascii=False, separators=(",", ":")),
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
            (
                _new_id(),
                session_id,
                attempt_id,
                xp,
                f"reward:{body.event_id}",
                timestamp,
            ),
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
        question_set = db.execute(
            """SELECT * FROM question_sets
               WHERE question_set_id=? AND version=?""",
            (session["question_set_id"], session["question_set_version"]),
        ).fetchone()
        question_count = len(_json_list(question_set["question_ids_json"]))
        attempt_count = db.execute(
            "SELECT COUNT(*) FROM question_attempts WHERE session_id=?", (session_id,)
        ).fetchone()[0]
        if attempt_count != question_count:
            raise HTTPException(status_code=409, detail="Answer every question before completion")
        completed_at = datetime.now(timezone.utc)
        started_at = datetime.fromisoformat(session["started_at"])
        duration_ms = max(0, int((completed_at - started_at).total_seconds() * 1000))
        old_best = personal_best(
            db,
            session["question_set_id"],
            session["question_set_version"],
            session["ruleset_version"],
            exclude_session_id=session_id,
        )
        is_personal_best = old_best is None or score_is_better(
            session["correct_count"],
            duration_ms,
            old_best["correct_count"],
            old_best["duration_ms"],
        )
        result: dict[str, object] = {
            "session_id": session_id,
            "question_set_id": session["question_set_id"],
            "question_set_version": session["question_set_version"],
            "ruleset_version": session["ruleset_version"],
            "completed_at": completed_at.isoformat(),
            "duration_ms": duration_ms,
            "question_count": question_count,
            "correct_count": session["correct_count"],
            "max_streak": session["max_streak"],
            "xp_earned": session["xp_earned"],
            "is_personal_best": is_personal_best,
            "saved": True,
        }
        result_json = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
        db.execute(
            """UPDATE game_sessions SET
                status='completed',completed_at=?,duration_ms=?,completion_event_id=?,
                completion_result_json=?,updated_at=? WHERE session_id=?""",
            (
                completed_at.isoformat(),
                duration_ms,
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
                "duration_ms": duration_ms,
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
        result.update(
            {
                "status": session["status"],
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
        if recent is not None:
            best = personal_best(
                db,
                recent["question_set_id"],
                recent["question_set_version"],
                recent["ruleset_version"],
            )
        else:
            best = None
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
        "recent_game": (
            json.loads(recent["completion_result_json"]) if recent is not None else None
        ),
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
