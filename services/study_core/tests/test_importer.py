from pathlib import Path
from app.importer import import_topics
from app.database import connect


def test_read_only_metadata_import(tmp_path, monkeypatch):
    repo=tmp_path / "course"
    maso=repo / "maso"
    maso.mkdir(parents=True)
    topic=maso / "01-1_first_concept.md"
    topic.write_text("# Test topic\n## Q1\n",encoding="utf-8")
    before=topic.read_bytes()
    monkeypatch.setenv('LEARNING_OS_DB',str(tmp_path / 'db.sqlite'))
    result=import_topics(str(repo))
    assert result['imported_topic_files']==1
    assert topic.read_bytes()==before
    with connect() as db:
        row=db.execute('SELECT relative_path,title,sha256 FROM course_sources').fetchone()
    assert row['relative_path']=='maso/01-1_first_concept.md'
    assert len(row['sha256'])==64
