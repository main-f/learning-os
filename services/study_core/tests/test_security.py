import json
from pathlib import Path

import pytest

from app.audit_public_build import audit_public_build
from app.database import connect


def test_public_build_rejects_sqlite_and_does_not_contain_private_prompts(imported_course, tmp_path):
    _course, database, _report, _result = imported_course
    dist = tmp_path / "dist"
    assets = dist / "assets"
    assets.mkdir(parents=True)
    (dist / "index.html").write_text("<main>Public shell</main>", encoding="utf-8")
    (assets / "app.js").write_text("console.log('safe shell')", encoding="utf-8")
    audit = audit_public_build(dist, database)
    assert audit["private_questions_checked"] == 12

    leaked = dist / "learning.sqlite"
    leaked.write_bytes(Path(database).read_bytes())
    with pytest.raises(ValueError, match="SQLite"):
        audit_public_build(dist, database)


def test_public_build_rejects_private_english_options_and_chinese_drafts(
    imported_course, tmp_path
):
    _course, database, _report, _result = imported_course
    with connect() as db:
        question = db.execute(
            "SELECT question_id,options_json FROM questions ORDER BY question_id LIMIT 1"
        ).fetchone()
        db.execute(
            """UPDATE questions SET prompt_zh=?,options_zh_json=?,translation_status='draft'
               WHERE question_id=?""",
            (
                "仅用于泄漏审计的合成中文题干",
                '["合成中文一","合成中文二","合成中文三","合成中文四"]',
                question["question_id"],
            ),
        )
    dist = tmp_path / "dist"
    dist.mkdir()
    first_english_option = json.loads(question["options_json"])[0]
    (dist / "index.html").write_text(first_english_option, encoding="utf-8")
    with pytest.raises(ValueError, match="private question"):
        audit_public_build(dist, database)
    (dist / "index.html").write_text("仅用于泄漏审计的合成中文题干", encoding="utf-8")
    with pytest.raises(ValueError, match="private question"):
        audit_public_build(dist, database)

