"""Learning OS local-only P0 service; never put this API on the public Internet."""
import json
from contextlib import asynccontextmanager
import uuid
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from .database import connect, initialize

@asynccontextmanager
async def lifespan(_app: FastAPI):
    initialize()
    with connect() as db:
        db.execute("""INSERT OR IGNORE INTO tasks(id,title,minutes,status,created_at)
            VALUES (?,?,?,?,?)""", (
            "cybersecurity-start", "打开 Cyber Security，完成一个 10 分钟知识点", 10,
            "pending", now_iso()))
    yield


app = FastAPI(title="Rae Learning OS / Study Core", version="0.1.0", lifespan=lifespan)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class SessionInput(BaseModel):
    task_id: str
    duration_minutes: int = Field(ge=1, le=480)
    evidence_note: str = Field(min_length=5, max_length=2000)
    activity_type: str = Field(default="study", pattern="^(study|demo_game|quiz)$")


@app.get("/health")
def health():
    return {"ok": True, "service": "study-core"}


@app.get("/api/v1/tasks")
def tasks():
    with connect() as db:
        rows = db.execute("SELECT id,title,minutes,status,completed_at FROM tasks ORDER BY status,id").fetchall()
    return {"items": [dict(r) for r in rows]}


@app.get("/api/v1/summary")
def summary():
    local = datetime.now(ZoneInfo("Europe/Helsinki"))
    sleep_limit = local.replace(hour=22, minute=0, second=0, microsecond=0)
    # This is time until the sleep boundary, NOT net study availability.
    minutes_to_sleep = max(0, int((sleep_limit-local).total_seconds()//60))
    with connect() as db:
        total = db.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        done = db.execute("SELECT COUNT(*) FROM tasks WHERE status='completed'").fetchone()[0]
        sources = db.execute("SELECT COUNT(*) FROM course_sources").fetchone()[0]
        sessions = db.execute("SELECT COUNT(*) FROM study_sessions WHERE activity_type!='demo_game'").fetchone()[0]
    return {
        "timezone": "Europe/Helsinki", "last_updated_at": now_iso(),
        "task_total": total, "task_completed": done, "imported_source_count": sources,
        "recorded_learning_sessions": sessions,
        "minutes_until_sleep_boundary": minutes_to_sleep,
        "net_available_study_minutes": None,  # Requires actual calendar and commitments
        "official_grade": None, "estimated_grade": None, "exam_deadline": None,
        "status_note": "尚未完成官方成绩和考试日期校验；严禁将示例数据当成真实成绩"
    }


@app.post("/api/v1/sessions", status_code=201)
def create_session(body: SessionInput):
    session_id = str(uuid.uuid4())
    event_id = str(uuid.uuid4())
    timestamp = now_iso()
    with connect() as db:
        task = db.execute("SELECT status FROM tasks WHERE id=?", (body.task_id,)).fetchone()
        if task is None:
            raise HTTPException(status_code=404, detail="Unknown task")
        db.execute("""INSERT INTO study_sessions
            (id,task_id,duration_minutes,evidence_note,activity_type,created_at)
            VALUES (?,?,?,?,?,?)""", (session_id,body.task_id,body.duration_minutes,body.evidence_note,body.activity_type,timestamp))
        payload = {"session_id":session_id,"task_id":body.task_id,"activity_type":body.activity_type}
        db.execute("INSERT INTO event_outbox(id,type,payload_json,created_at) VALUES(?,?,?,?)",
                   (event_id,"study.session_recorded",json.dumps(payload),timestamp))
        # Deliberately do not turn "demo_game" into task completion or academic mastery.
        if body.activity_type != "demo_game":
            db.execute("UPDATE tasks SET status='completed',completed_at=? WHERE id=? AND status='pending'",
                       (timestamp,body.task_id))
    return {"session_id":session_id, "event_id":event_id, "task_marked_completed":body.activity_type!="demo_game"}
