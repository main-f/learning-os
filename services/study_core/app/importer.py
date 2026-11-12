"""Read-only source metadata importer. Does not publish PDF/text to GitHub Pages."""
import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
import re
from .database import connect, initialize

TOPIC_PATTERN = re.compile(r"^[0-9]{2}-[0-9]_.+\.md$")


def import_topics(course_root: str | None = None) -> dict:
    if course_root is None:
        course_root = os.getenv("COURSE_ROOT", "")
    if not course_root:
        raise ValueError("COURSE_ROOT is missing")
    root = Path(course_root).expanduser().resolve()
    maso = root / "maso"
    if not maso.is_dir():
        raise ValueError(f"Expected folder absent: {maso}")
    initialize()
    found = 0
    with connect() as db:
        for source in sorted(maso.iterdir()):
            if not source.is_file() or not TOPIC_PATTERN.match(source.name):
                continue
            raw = source.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            rel = str(source.relative_to(root))
            source_id = f"cybersecurity:{source.stem}"
            db.execute("""INSERT INTO course_sources(source_id,relative_path,title,sha256,imported_at)
                          VALUES (?,?,?,?,?)
                          ON CONFLICT(source_id) DO UPDATE SET sha256=excluded.sha256,
                          imported_at=excluded.imported_at,title=excluded.title""",
                       (source_id,rel,source.stem.replace("_"," "),sha,
                        datetime.now(timezone.utc).isoformat()))
            found += 1
    return {"imported_topic_files":found,"course_root":str(root),
            "note":"Metadata only. MCQ import needs answer verification before play."}
