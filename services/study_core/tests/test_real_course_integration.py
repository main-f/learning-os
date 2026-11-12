from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import pytest
from fastapi.testclient import TestClient

from app.database import connect
from app.importer import import_course
from app.main import app


def test_real_course_counts_and_read_only_status(tmp_path, monkeypatch):
    configured = os.getenv("COURSE_ROOT")
    if not configured:
        pytest.skip("Set COURSE_ROOT to run the private read-only integration test")
    course_root = Path(configured).resolve()
    before = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=course_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    monkeypatch.setenv("LEARNING_OS_DB", str(tmp_path / "real.sqlite"))
    monkeypatch.setenv("LEARNING_OS_IMPORT_REPORT", str(tmp_path / "import_report.json"))
    result = import_course(str(course_root))
    assert result["topic_count"] == 33
    assert result["candidate_question_count"] == 141
    assert result["source_verified_count"] == 11
    assert result["duplicate_count"] == 0
    assert result["disputed_count"] == 0
    assert result["failed_count"] == 0
    assert len(result["selected_question_ids"]) == 10

    with TestClient(app) as client:
        started = client.post("/api/v1/game-sessions/start", json={})
        assert started.status_code == 201
        game = started.json()
        assert "correct_options" not in json.dumps(game)
        for index, question in enumerate(game["questions"]):
            with connect() as db:
                correct = json.loads(
                    db.execute(
                        "SELECT correct_options_json FROM questions WHERE question_id=?",
                        (question["question_id"],),
                    ).fetchone()[0]
                )
            attempt = client.post(
                f"/api/v1/game-sessions/{game['session_id']}/attempts",
                json={
                    "event_id": f"real-course-e2e-attempt-{index}",
                    "question_id": question["question_id"],
                    "chosen_options": correct,
                    "response_ms": 100 + index,
                },
            )
            assert attempt.status_code == 201
        completed = client.post(
            f"/api/v1/game-sessions/{game['session_id']}/complete",
            json={"event_id": "real-course-e2e-complete"},
        )
        assert completed.status_code == 200
        dashboard = client.get("/api/v1/dashboard").json()
        assert dashboard["recent_game"]["session_id"] == game["session_id"]
        assert dashboard["official_grade"] is None
        assert dashboard["mastery"] == "unknown"

    after = subprocess.run(
        ["git", "status", "--porcelain=v1"],
        cwd=course_root,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert before == after

