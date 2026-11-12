from __future__ import annotations

import json
from pathlib import Path

from app.database import connect
from app.importer import import_course, parse_markdown_topic, parse_saved_questions, reconcile_questions


def file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_markdown_parser_keeps_repeated_one_options_in_source_order(synthetic_course):
    source = synthetic_course.root / "maso" / "01-1_synthetic.md"
    topic = parse_markdown_topic(source, synthetic_course.root)
    assert len(topic.questions) == 5
    assert topic.questions[0].local_question_number == 1
    assert topic.questions[0].options == [
        "Synthetic choice 01-1-1-A",
        "Synthetic choice 01-1-1-B",
        "Synthetic choice 01-1-1-C",
        "Synthetic choice 01-1-1-D",
    ]
    assert topic.questions[0].markdown_answer_value is None
    assert "合成测试推理" in (topic.questions[0].learner_reasoning or "")


def test_html_answer_number_and_text_are_both_checked(synthetic_course):
    markdown = parse_markdown_topic(
        synthetic_course.root / "maso" / "01-1_synthetic.md", synthetic_course.root
    ).questions
    html_path = next(
        (synthetic_course.root / "maso" / "0709" / "maso_html").glob(
            "MASO _ Synthetic 01-1_files/oheismateriaali.html"
        )
    )
    saved = parse_saved_questions(html_path, synthetic_course.root)
    assert reconcile_questions(markdown, saved) == []
    assert all(question.answer_validation_status == "source_verified" for question in markdown)
    assert markdown[0].correct_options == [synthetic_course.correct_by_id[markdown[0].question_id]]


def test_mismatched_answer_title_becomes_disputed(tmp_path, monkeypatch, course_factory):
    disputed_id = "cyber-security:01-1:q1"
    course = course_factory(disputed_id)
    monkeypatch.setenv("LEARNING_OS_DB", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("LEARNING_OS_IMPORT_REPORT", str(tmp_path / "report.json"))
    report = import_course(str(course.root))
    assert report["source_verified_count"] == 10
    assert report["disputed_count"] == 1
    with connect() as db:
        row = db.execute(
            "SELECT answer_validation_status,correct_options_json FROM questions WHERE question_id=?",
            (disputed_id,),
        ).fetchone()
    assert row["answer_validation_status"] == "disputed"
    assert json.loads(row["correct_options_json"]) == []


def test_only_source_verified_private_questions_enter_first_set(imported_course):
    _course, _database, _report_path, report = imported_course
    assert report["source_verified_count"] == 11
    assert len(report["selected_question_ids"]) == 10
    with connect() as db:
        question_set = db.execute("SELECT * FROM question_sets").fetchone()
        selected = json.loads(question_set["question_ids_json"])
        rows = db.execute(
            "SELECT question_id,answer_validation_status,distribution_scope FROM questions"
        ).fetchall()
    status = {row["question_id"]: row for row in rows}
    assert len(selected) == 10
    assert all(status[item]["answer_validation_status"] == "source_verified" for item in selected)
    assert all(status[item]["distribution_scope"] == "private_only" for item in selected)
    assert "cyber-security:01-3:q1" not in selected


def test_importer_does_not_modify_course_root(tmp_path, monkeypatch, synthetic_course):
    before = file_snapshot(synthetic_course.root)
    monkeypatch.setenv("LEARNING_OS_DB", str(tmp_path / "state" / "db.sqlite"))
    monkeypatch.setenv("LEARNING_OS_IMPORT_REPORT", str(tmp_path / "state" / "report.json"))
    import_course(str(synthetic_course.root))
    assert file_snapshot(synthetic_course.root) == before


def test_private_report_contains_counts_and_ids_but_not_prompts(imported_course):
    course, _database, report_path, report = imported_course
    payload = report_path.read_text(encoding="utf-8")
    parsed = json.loads(payload)
    assert parsed["topic_count"] == 3
    assert parsed["candidate_question_count"] == 12
    assert parsed["source_verified_count"] == 11
    assert parsed["failed_count"] == 0
    assert parsed["source_paths"]
    assert parsed["selected_question_ids"] == report["selected_question_ids"]
    assert all(prompt not in payload for prompt in course.prompts_by_id.values())
