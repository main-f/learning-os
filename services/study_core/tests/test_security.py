from pathlib import Path

import pytest

from app.audit_public_build import audit_public_build


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

