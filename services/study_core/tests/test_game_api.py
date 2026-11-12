from __future__ import annotations

import json

from app.database import connect, utc_now_iso
from app.game import personal_best, score_is_better


def start(client):
    response = client.post("/api/v1/game-sessions/start", json={})
    assert response.status_code == 201, response.text
    return response.json()


def answer(client, game, course, index, *, correct=True, event_id=None):
    question = game["questions"][index]
    correct_option = course.correct_by_id[question["question_id"]]
    chosen = correct_option if correct else correct_option % 4 + 1
    payload = {
        "event_id": event_id or f"attempt-{game['session_id']}-{index}",
        "question_id": question["question_id"],
        "chosen_options": [chosen],
        "response_ms": 100 + index,
    }
    response = client.post(
        f"/api/v1/game-sessions/{game['session_id']}/attempts", json=payload
    )
    assert response.status_code == 201, response.text
    return response.json(), payload


def finish_all(client, game, course):
    results = []
    for index in range(game["question_count"]):
        result, _payload = answer(client, game, course, index)
        results.append(result)
    return results


def test_start_never_returns_correct_answers(api_client):
    client, _course, _database, _report, _result = api_client
    game = start(client)
    serialized = json.dumps(game)
    assert game["question_count"] == 10
    assert "correct_options" not in serialized
    assert "explanation" not in serialized


def test_attempt_is_scored_on_server_and_returns_auditable_feedback(api_client):
    client, course, _database, _report, _result = api_client
    game = start(client)
    result, _payload = answer(client, game, course, 0, correct=True)
    assert result["correct"] is True
    assert result["correct_options"] == [course.correct_by_id[result["question_id"]]]
    assert result["source_ref"].startswith("maso/")
    assert result["explanation"] == "详细解析待人工复核"
    assert result["streak"] == 1
    assert result["xp_earned"] == 10
    assert result["saved"] is True


def test_duplicate_attempt_event_returns_same_result_without_double_xp(api_client):
    client, course, _database, _report, _result = api_client
    game = start(client)
    first, payload = answer(client, game, course, 0, event_id="same-attempt-event")
    replay = client.post(
        f"/api/v1/game-sessions/{game['session_id']}/attempts", json=payload
    )
    assert replay.status_code == 201
    assert replay.json() == first
    with connect() as db:
        attempt_count = db.execute(
            "SELECT COUNT(*) FROM question_attempts WHERE session_id=?", (game["session_id"],)
        ).fetchone()[0]
        reward_count = db.execute(
            "SELECT COUNT(*) FROM reward_events WHERE session_id=?", (game["session_id"],)
        ).fetchone()[0]
        xp = db.execute(
            "SELECT xp_earned FROM game_sessions WHERE session_id=?", (game["session_id"],)
        ).fetchone()[0]
    assert (attempt_count, reward_count, xp) == (1, 1, first["xp_earned"])


def test_wrong_answer_resets_streak(api_client):
    client, course, _database, _report, _result = api_client
    game = start(client)
    first, _ = answer(client, game, course, 0, correct=True)
    second, _ = answer(client, game, course, 1, correct=True)
    third, _ = answer(client, game, course, 2, correct=False)
    fourth, _ = answer(client, game, course, 3, correct=True)
    assert [first["streak"], second["streak"], third["streak"], fourth["streak"]] == [1, 2, 0, 1]
    assert third["xp_earned"] == 0


def test_end_to_end_start_ten_attempts_complete_dashboard_and_idempotent_complete(api_client):
    client, course, _database, _report, _result = api_client
    game = start(client)
    attempts = finish_all(client, game, course)
    assert len(attempts) == 10
    completion_payload = {"event_id": "complete-event-1"}
    first = client.post(
        f"/api/v1/game-sessions/{game['session_id']}/complete", json=completion_payload
    )
    replay = client.post(
        f"/api/v1/game-sessions/{game['session_id']}/complete", json=completion_payload
    )
    assert first.status_code == replay.status_code == 200
    assert replay.json() == first.json()
    completed = first.json()
    assert completed["correct_count"] == 10
    assert completed["is_personal_best"] is True
    result = client.get(f"/api/v1/game-sessions/{game['session_id']}/result").json()
    assert result["status"] == "completed"
    assert len(result["attempts"]) == 10
    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["recent_game"]["session_id"] == game["session_id"]
    assert dashboard["personal_best"]["session_id"] == game["session_id"]
    with connect() as db:
        completions = db.execute(
            "SELECT COUNT(*) FROM event_outbox WHERE type='game.session.completed'"
        ).fetchone()[0]
    assert completions == 1


def test_personal_best_compares_only_same_set_and_rules_and_correctness_wins(imported_course):
    _course, _database, _report, result = imported_course
    version = result["question_set_version"]
    timestamp = utc_now_iso()
    with connect() as db:
        base = db.execute(
            "SELECT question_ids_json FROM question_sets WHERE version=?", (version,)
        ).fetchone()[0]
        db.execute(
            "INSERT INTO question_sets VALUES(?,?,?,?,?,1)",
            ("cyber-security-exam1-speed-run", "other-version", "1", base, timestamp),
        )

        def insert_session(session_id, set_version, rules, correct_count, duration):
            db.execute(
                """INSERT INTO game_sessions(
                    session_id,question_set_id,question_set_version,ruleset_version,
                    started_at,completed_at,duration_ms,correct_count,max_streak,
                    xp_earned,status,completion_event_id,completion_result_json,
                    created_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,1000,'completed',?,?,?,?)""",
                (
                    session_id,
                    "cyber-security-exam1-speed-run",
                    set_version,
                    rules,
                    timestamp,
                    timestamp,
                    duration,
                    correct_count,
                    correct_count,
                    f"complete-{session_id}",
                    "{}",
                    timestamp,
                    timestamp,
                ),
            )

        insert_session("fast-nine", version, "1", 9, 1)
        insert_session("slow-ten", version, "1", 10, 99_999)
        insert_session("other-rules", version, "2", 10, 1)
        insert_session("other-set", "other-version", "1", 10, 1)
        best = personal_best(db, "cyber-security-exam1-speed-run", version, "1")
    assert best["session_id"] == "slow-ten"
    assert score_is_better(10, 99_999, 9, 1) is True


def test_even_1000_xp_cannot_change_official_grade_or_unknown_mastery(api_client):
    client, _course, _database, _report, _result = api_client
    game = start(client)
    with connect() as db:
        db.execute(
            "UPDATE game_sessions SET xp_earned=1000 WHERE session_id=?", (game["session_id"],)
        )
    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["official_grade"] is None
    assert dashboard["official_grade_status"] == "pending_confirmation"
    assert dashboard["mastery"] == "unknown"
    assert dashboard["xp_is_official_grade"] is False

