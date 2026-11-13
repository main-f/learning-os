from __future__ import annotations

import json

from app.database import connect, utc_now_iso
from app.translation_reviews import apply_translation_review_pack


def make_pack(path, *, approved: bool, attributable: bool):
    with connect() as db:
        rows = db.execute(
            """SELECT question_id,content_hash,prompt,options_json FROM questions
               WHERE answer_validation_status='source_verified'
               ORDER BY question_id"""
        ).fetchall()
    payload = {
        "schema_version": 1,
        "translation_version": "synthetic-zh-v1",
        "questions": [
            {
                "question_id": row["question_id"],
                "content_hash": row["content_hash"],
                "prompt_en": row["prompt"],
                "options_en": json.loads(row["options_json"]),
                "prompt_zh": f"合成题干 {row['question_id']}",
                "options_zh": [f"合成选项 {number}" for number in range(1, 5)],
                "key_terms": ["synthetic：合成"],
                "translation_risks": ["仅用于测试。"],
                "review": {
                    "approve": approved,
                    "dispute": False,
                    "reviewer": "test-reviewer" if attributable else None,
                    "reviewed_at": utc_now_iso() if attributable else None,
                    "notes": "",
                },
            }
            for row in rows
        ],
    }
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def test_draft_pack_cannot_self_approve(imported_course, tmp_path):
    path = tmp_path / "draft.json"
    make_pack(path, approved=False, attributable=False)
    counts = apply_translation_review_pack(path)
    assert counts == {"draft": 11, "human_verified": 0, "disputed": 0}
    with connect() as db:
        statuses = {
            row[0] for row in db.execute("SELECT translation_status FROM questions")
        }
    assert statuses == {"draft", "missing"}


def test_approval_requires_reviewer_and_timestamp(imported_course, tmp_path):
    incomplete = tmp_path / "incomplete.json"
    make_pack(incomplete, approved=True, attributable=False)
    assert apply_translation_review_pack(incomplete)["human_verified"] == 0

    approved = tmp_path / "approved.json"
    make_pack(approved, approved=True, attributable=True)
    counts = apply_translation_review_pack(approved)
    assert counts["human_verified"] == 11
    with connect() as db:
        verified = db.execute(
            "SELECT COUNT(*) FROM questions WHERE translation_status='human_verified'"
        ).fetchone()[0]
    assert verified == 11
