from __future__ import annotations

import json

from app.database import connect, utc_now_iso
from app.game import (
    build_session_presentation,
    calculate_ranked_duration,
    personal_best,
    score_is_better,
    time_multiplier_for,
)


def start(client, assistance_mode="none"):
    response = client.post(
        "/api/v1/game-sessions/start", json={"assistance_mode": assistance_mode}
    )
    assert response.status_code == 201, response.text
    return response.json()


def chosen_token(game, course, index, *, correct=True):
    question = game["questions"][index]
    correct_index = course.correct_by_id[question["question_id"]]
    correct_text = course.options_by_id[question["question_id"]][correct_index - 1]
    correct_item = next(item for item in question["options"] if item["text"] == correct_text)
    if correct:
        return correct_item["option_token"]
    return next(
        item["option_token"]
        for item in question["options"]
        if item["option_token"] != correct_item["option_token"]
    )


def answer(client, game, course, index, *, correct=True, event_id=None):
    question = game["questions"][index]
    payload = {
        "event_id": event_id or f"attempt-{game['session_id']}-{index}",
        "question_id": question["question_id"],
        "chosen_option_tokens": [chosen_token(game, course, index, correct=correct)],
        "response_ms": 100 + index,
    }
    response = client.post(
        f"/api/v1/game-sessions/{game['session_id']}/attempts", json=payload
    )
    assert response.status_code == 201, response.text
    return response.json(), payload


def finish_all(client, game, course):
    return [answer(client, game, course, index)[0] for index in range(game["question_count"])]


def mark_synthetic_translations_verified(game):
    with connect() as db:
        for question in game["questions"]:
            options_zh = [f"合成译文 {index}" for index in range(1, 5)]
            db.execute(
                """UPDATE questions SET prompt_zh=?,options_zh_json=?,
                   translation_status='human_verified',translation_version='test-v1',
                   translation_reviewed_at=? WHERE question_id=?""",
                (
                    f"合成题干译文 {question['question_id']}",
                    json.dumps(options_zh, ensure_ascii=False),
                    utc_now_iso(),
                    question["question_id"],
                ),
            )


def test_seeded_shuffle_is_repeatable_and_different_seeds_vary():
    ids = [f"q{number}" for number in range(10)]
    first = build_session_presentation(ids, "fixed-seed")
    assert first == build_session_presentation(ids, "fixed-seed")
    assert first != build_session_presentation(ids, "different-seed")
    assert sorted(first[0]) == ids
    assert all(sorted(order) == [1, 2, 3, 4] for order in first[1].values())


def test_start_randomizes_server_side_and_never_returns_answers(api_client):
    client, _course, _database, _report, _result = api_client
    first = start(client)
    second = start(client)
    serialized = json.dumps(first)
    assert first["question_count"] == 10
    assert first["ruleset_version"] == "2"
    assert "correct_option" not in serialized
    assert "shuffle_seed" not in serialized
    assert all(
        set(option) == {"option_token", "text"}
        for question in first["questions"]
        for option in question["options"]
    )
    with connect() as db:
        seeds = [
            db.execute(
                "SELECT shuffle_seed FROM game_sessions WHERE session_id=?", (game["session_id"],)
            ).fetchone()[0]
            for game in (first, second)
        ]
    assert seeds[0] != seeds[1]


def test_option_token_scores_correctly_after_options_move_and_audits_order(api_client):
    client, course, _database, _report, _result = api_client
    game = start(client)
    result, payload = answer(client, game, course, 0, correct=True)
    assert result["correct"] is True
    assert result["correct_option_tokens"] == payload["chosen_option_tokens"]
    assert result["source_ref"].startswith("maso/")
    assert result["explanation"] == "详细解析待人工复核"
    assert result["streak"] == 1
    assert result["xp_earned"] == 10
    with connect() as db:
        stored = db.execute(
            """SELECT chosen_options_json,chosen_option_tokens_json,
                      presentation_order_json,assistance_mode,evidence_mode
               FROM question_attempts WHERE event_id=?""",
            (payload["event_id"],),
        ).fetchone()
    assert json.loads(stored["chosen_options_json"]) == [
        course.correct_by_id[result["question_id"]]
    ]
    assert json.loads(stored["chosen_option_tokens_json"]) == payload["chosen_option_tokens"]
    assert len(json.loads(stored["presentation_order_json"])) == 4
    assert (stored["assistance_mode"], stored["evidence_mode"]) == ("none", "unassisted")


def test_numeric_array_index_is_not_an_accepted_submission(api_client):
    client, _course, _database, _report, _result = api_client
    game = start(client)
    question = game["questions"][0]
    response = client.post(
        f"/api/v1/game-sessions/{game['session_id']}/attempts",
        json={
            "event_id": "legacy-index",
            "question_id": question["question_id"],
            "chosen_options": [1],
            "response_ms": 10,
        },
    )
    assert response.status_code == 422


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
    results = [
        answer(client, game, course, 0, correct=True)[0],
        answer(client, game, course, 1, correct=True)[0],
        answer(client, game, course, 2, correct=False)[0],
        answer(client, game, course, 3, correct=True)[0],
    ]
    assert [item["streak"] for item in results] == [1, 2, 0, 1]
    assert results[2]["xp_earned"] == 0


def test_active_session_restore_preserves_question_and_option_order(api_client):
    client, course, _database, _report, _result = api_client
    game = start(client)
    answer(client, game, course, 0)
    restored = client.get(f"/api/v1/game-sessions/{game['session_id']}/result")
    assert restored.status_code == 200
    body = restored.json()
    assert body["status"] == "active"
    assert body["started_at"] == game["started_at"]
    assert body["question_order"] == game["question_order"]
    assert body["questions"] == game["questions"]
    assert len(body["attempts"]) == 1
    assert body["raw_duration_ms"] >= 0


def test_unreviewed_translations_are_rejected_and_not_returned(api_client):
    client, _course, _database, _report, _result = api_client
    config = client.get("/api/v1/game-config").json()
    assert config["assistance"]["zh_translation_available"] is False
    response = client.post(
        "/api/v1/game-sessions/start", json={"assistance_mode": "zh_translation"}
    )
    assert response.status_code == 409
    assert "待人工复核" in response.json()["detail"]
    game = start(client)
    assert "prompt_zh" not in json.dumps(game, ensure_ascii=False)


def test_human_verified_translations_return_bilingual_and_mark_assisted_evidence(api_client):
    client, course, _database, _report, _result = api_client
    baseline = start(client)
    mark_synthetic_translations_verified(baseline)
    game = start(client, "zh_translation")
    assert game["assistance_mode"] == "zh_translation"
    assert game["time_multiplier"] == 1.3
    assert all("prompt" in question and "prompt_zh" in question for question in game["questions"])
    assert all(
        "text" in option and "text_zh" in option
        for question in game["questions"]
        for option in question["options"]
    )
    result, _payload = answer(client, game, course, 0)
    assert result["evidence_mode"] == "assisted"
    with connect() as db:
        stored = db.execute(
            "SELECT assistance_mode,evidence_mode FROM question_attempts WHERE attempt_id=?",
            (result["attempt_id"],),
        ).fetchone()
    assert tuple(stored) == ("zh_translation", "assisted")


def test_end_to_end_complete_is_idempotent_and_dashboard_uses_v2_fields(api_client):
    client, course, _database, _report, _result = api_client
    game = start(client)
    assert len(finish_all(client, game, course)) == 10
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
    assert completed["assistance_mode"] == "none"
    assert completed["time_multiplier"] == 1.0
    assert completed["raw_duration_ms"] == completed["ranked_duration_ms"]
    assert completed["is_personal_best"] is True
    result = client.get(f"/api/v1/game-sessions/{game['session_id']}/result").json()
    assert result["status"] == "completed"
    assert len(result["attempts"]) == 10
    assert result["questions"] == game["questions"]
    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["recent_game"]["session_id"] == game["session_id"]
    assert dashboard["personal_best"]["session_id"] == game["session_id"]
    with connect() as db:
        completions = db.execute(
            "SELECT COUNT(*) FROM event_outbox WHERE type='game.session.completed'"
        ).fetchone()[0]
    assert completions == 1


def test_multipliers_and_ranked_rounding_are_exact():
    assert time_multiplier_for("none") == 1.0
    assert time_multiplier_for("zh_translation") == 1.3
    assert calculate_ranked_duration(10_001, "none") == 10_001
    assert calculate_ranked_duration(10_001, "zh_translation") == 13_001
    assert calculate_ranked_duration(10_005, "zh_translation") == 13_007


def test_personal_best_uses_ranked_time_and_isolates_v1_v2(imported_course):
    _course, _database, _report, imported = imported_course
    version = imported["question_set_version"]
    timestamp = utc_now_iso()

    def insert_session(
        db, session_id, rules, correct_count, raw, ranked, assistance="none"
    ):
        db.execute(
            """INSERT INTO game_sessions(
                session_id,question_set_id,question_set_version,ruleset_version,
                started_at,completed_at,duration_ms,raw_duration_ms,ranked_duration_ms,
                correct_count,max_streak,xp_earned,status,completion_event_id,
                completion_result_json,assistance_mode,time_multiplier,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,1000,'completed',?,?,?,?,?,?)""",
            (
                session_id,
                "cyber-security-exam1-speed-run",
                version,
                rules,
                timestamp,
                timestamp,
                raw,
                raw,
                ranked,
                correct_count,
                correct_count,
                f"complete-{session_id}",
                "{}",
                assistance,
                1.3 if assistance == "zh_translation" else 1.0,
                timestamp,
                timestamp,
            ),
        )

    with connect() as db:
        insert_session(db, "fast-raw-assisted", "2", 10, 1_000, 1_300, "zh_translation")
        insert_session(db, "slower-raw-ranked-best", "2", 10, 1_200, 1_200)
        insert_session(db, "fast-nine", "2", 9, 1, 1)
        insert_session(db, "v1-record", "1", 10, 1, 1)
        best_v2 = personal_best(db, "cyber-security-exam1-speed-run", version, "2")
        best_v1 = personal_best(db, "cyber-security-exam1-speed-run", version, "1")
    assert best_v2["session_id"] == "slower-raw-ranked-best"
    assert best_v1["session_id"] == "v1-record"
    assert score_is_better(10, 99_999, 9, 1) is True


def test_assisted_xp_cannot_change_official_grade_or_unknown_mastery(api_client):
    client, _course, _database, _report, _result = api_client
    game = start(client)
    with connect() as db:
        db.execute(
            """UPDATE game_sessions SET xp_earned=1000,assistance_mode='zh_translation',
               time_multiplier=1.3 WHERE session_id=?""",
            (game["session_id"],),
        )
    dashboard = client.get("/api/v1/dashboard").json()
    assert dashboard["official_grade"] is None
    assert dashboard["official_grade_status"] == "pending_confirmation"
    assert dashboard["mastery"] == "unknown"
    assert dashboard["xp_is_official_grade"] is False
