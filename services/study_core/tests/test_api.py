import os
from fastapi.testclient import TestClient
from app.main import app


def test_study_session_does_not_fabricate_grade(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_OS_DB", str(tmp_path / "study.sqlite"))
    with TestClient(app) as c:
        s=c.get('/api/v1/summary').json()
        assert s['official_grade'] is None
        assert s['estimated_grade'] is None
        assert s['exam_deadline'] is None
        assert s['task_total'] >= 1
        r=c.post('/api/v1/sessions',json={"task_id":"cybersecurity-start","duration_minutes":10,
                       "evidence_note":"Completed a 10-minute study session","activity_type":"study"})
        assert r.status_code==201
        assert c.get('/api/v1/summary').json()['task_completed']==1
        assert c.get('/api/v1/summary').json()['official_grade'] is None


def test_demo_does_not_complete_task(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_OS_DB", str(tmp_path / "study.sqlite"))
    with TestClient(app) as c:
        r=c.post('/api/v1/sessions',json={"task_id":"cybersecurity-start","duration_minutes":2,
                       "evidence_note":"Played the demonstration game", "activity_type":"demo_game"})
        assert r.status_code==201
        assert c.get('/api/v1/summary').json()['task_completed']==0
        assert c.get('/api/v1/summary').json()['recorded_learning_sessions']==0


def test_missing_task_is_404(tmp_path, monkeypatch):
    monkeypatch.setenv("LEARNING_OS_DB", str(tmp_path / "study.sqlite"))
    with TestClient(app) as c:
        r=c.post('/api/v1/sessions',json={"task_id":"wrong","duration_minutes":10,
                      "evidence_note":"Read material", "activity_type":"study"})
        assert r.status_code==404
