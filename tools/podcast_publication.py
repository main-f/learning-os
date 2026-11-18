"""Allowlisted public podcast export. Does not import the private application/DB."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import wave


ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
MEDIA = re.compile(r"^media/([a-f0-9]{64})\.(m4a|mp3|wav)$")
EPISODE_FIELDS = {
    "id", "title", "description", "audio", "sha256", "duration_seconds", "published_at",
}
FORBIDDEN = (
    b"SQLite format 3", b"BEGIN PRIVATE KEY", b"github_pat_", b"ghp_",
    b"LEARNING_OS_DB=", b"STUDY_TELEGRAM_BOT_TOKEN=", b"storage_state.json",
)


def sha256(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def date_valid(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.tzinfo is not None
    except ValueError:
        return False


def validate_catalog(value: dict) -> dict:
    if (
        not isinstance(value, dict) or set(value) != {"schema_version", "generated_at", "episodes"}
        or value["schema_version"] != 1 or not date_valid(value["generated_at"])
        or not isinstance(value["episodes"], list) or len(value["episodes"]) > 14
    ):
        raise ValueError("Invalid public catalog")
    seen = set()
    for episode in value["episodes"]:
        if not isinstance(episode, dict) or set(episode) != EPISODE_FIELDS:
            raise ValueError("Unexpected public episode fields")
        if not isinstance(episode["id"], str) or not ID.fullmatch(episode["id"]) or episode["id"] in seen:
            raise ValueError("Invalid or duplicated episode ID")
        seen.add(episode["id"])
        if not isinstance(episode["title"], str) or not 1 <= len(episode["title"].strip()) <= 200:
            raise ValueError("Invalid episode title")
        if not isinstance(episode["description"], str) or len(episode["description"]) > 1000:
            raise ValueError("Invalid episode description")
        match = MEDIA.fullmatch(episode["audio"]) if isinstance(episode["audio"], str) else None
        if not match or match[1] != episode["sha256"]:
            raise ValueError("Audio must be a content-addressed relative media asset")
        duration = episode["duration_seconds"]
        if not isinstance(duration, (int, float)) or not 0 < duration <= 14_400:
            raise ValueError("Invalid duration")
        if not date_valid(episode["published_at"]):
            raise ValueError("Invalid publication timestamp")
    return value


def probe_duration(path: Path) -> float:
    with path.open("rb") as handle:
        head = handle.read(16)
    if head[:4] == b"RIFF" and head[8:12] == b"WAVE":
        with wave.open(str(path)) as audio:
            return audio.getnframes() / audio.getframerate()
    if Path("/usr/bin/afinfo").is_file():
        result = subprocess.run(["/usr/bin/afinfo", str(path)], capture_output=True, text=True, check=True, timeout=30)
        match = re.search(r"estimated duration:\s*([\d.]+)", result.stdout)
        if not match:
            raise ValueError("Cannot probe duration")
        return float(match[1])
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True, timeout=30,
    )
    return float(result.stdout.strip())


def build_bundle(allowlist: Path, media_root: Path, output: Path, cache: Path, *, encoding="aac128") -> dict:
    plan = json.loads(allowlist.read_text(encoding="utf-8"))
    if (
        plan.get("schema_version") != 1 or plan.get("authorization") != "user_requested_public_podcasts"
        or not isinstance(plan.get("episodes"), list) or not 1 <= len(plan["episodes"]) <= 14
    ):
        raise ValueError("Explicit publication allowlist required")
    root = media_root.resolve(strict=True)
    prepared = []
    for entry in plan["episodes"]:
        relative = Path(entry["source_relative"])
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("Unsafe source path")
        source = (root / relative).resolve(strict=True)
        if not source.is_file() or not source.is_relative_to(root):
            raise ValueError("Source escapes media root")
        if sha256(source) != entry["source_sha256"]:
            raise ValueError("Allowlisted source changed; new publication approval is required")
        duration = probe_duration(source)
        if not 0 < duration <= 14_400:
            raise ValueError("Source duration invalid")
        cache.mkdir(parents=True, exist_ok=True)
        if encoding == "aac128":
            encoded = cache / (entry["source_sha256"] + "-aac128.m4a")
            if not encoded.is_file():
                temporary = encoded.with_suffix(".part.m4a")
                temporary.unlink(missing_ok=True)
                subprocess.run(
                    ["/usr/bin/afconvert", "-f", "m4af", "-d", "aac ", "-b", "128000",
                     "-q", "127", str(source), str(temporary)],
                    capture_output=True, check=True, timeout=600,
                )
                temporary.replace(encoded)
        elif encoding == "copy":
            encoded = source
        else:
            raise ValueError("Unsupported encoding")
        actual_duration = probe_duration(encoded)
        if abs(actual_duration - duration) > max(2, duration * 0.005):
            raise ValueError("Encoded duration differs from the source")
        digest = sha256(encoded)
        episode = {
            "id": entry["id"], "title": entry["title"], "description": entry["description"],
            "audio": "media/" + digest + encoded.suffix.lower(), "sha256": digest,
            "duration_seconds": round(actual_duration, 3), "published_at": entry["published_at"],
        }
        prepared.append((episode, encoded))
    catalog = validate_catalog({
        "schema_version": 1, "generated_at": utc_now(), "episodes": [row[0] for row in prepared],
    })
    if output.exists() and any(output.iterdir()):
        raise ValueError("Use a new empty output directory")
    (output / "media").mkdir(parents=True, exist_ok=True)
    for episode, encoded in prepared:
        shutil.copyfile(encoded, output / episode["audio"])
    (output / "episodes.json").write_text(json.dumps(catalog, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return validate_bundle(output)


def validate_bundle(bundle: Path) -> dict:
    catalog = validate_catalog(json.loads((bundle / "episodes.json").read_text(encoding="utf-8")))
    expected = {episode["audio"] for episode in catalog["episodes"]}
    actual = {str(path.relative_to(bundle)) for path in (bundle / "media").rglob("*") if path.is_file()}
    if expected != actual:
        raise ValueError("Unlisted or missing audio assets")
    total = 0
    for episode in catalog["episodes"]:
        path = bundle / episode["audio"]
        if path.is_symlink() or not path.resolve().is_relative_to(bundle.resolve()) or sha256(path) != episode["sha256"]:
            raise ValueError("Audio asset failed SHA-256/path validation")
        with path.open("rb") as handle:
            header = handle.read(16)
        extension = path.suffix
        valid = (
            extension == ".m4a" and header[4:8] == b"ftyp"
            or extension == ".wav" and header[:4] == b"RIFF" and header[8:12] == b"WAVE"
            or extension == ".mp3" and (header[:3] == b"ID3" or header[:1] == b"\xff")
        )
        if not valid:
            raise ValueError("Unexpected audio container")
        total += path.stat().st_size
    return {"episodes": len(catalog["episodes"]), "media_bytes": total}


def audit_site(site: Path, database: Path | None = None, checklist: Path | None = None) -> dict:
    summary = validate_bundle(site)
    catalog = json.loads((site / "episodes.json").read_text(encoding="utf-8"))
    allowed_media = {episode["audio"] for episode in catalog["episodes"]}
    text_files = []
    for path in site.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symlink in public output")
        if not path.is_file():
            continue
        relative = path.relative_to(site).as_posix()
        if relative in allowed_media:
            continue
        allowed = relative in {"index.html", "episodes.json", "icon.svg", ".nojekyll"} or (
            relative.startswith("assets/") and path.suffix in {".js", ".css", ".svg", ".png", ".jpg", ".webp", ".woff2"}
        )
        if not allowed:
            raise ValueError("Unlisted file in public output: " + relative)
        raw = path.read_bytes()
        if any(marker in raw for marker in FORBIDDEN):
            raise ValueError("Private content marker in public output")
        try:
            text_files.append(raw.decode("utf-8"))
        except UnicodeError:
            pass
    private_strings = []
    checked_questions = 0
    if database:
        with sqlite3.connect("file:" + str(database.resolve()) + "?mode=ro", uri=True) as db:
            rows = db.execute("SELECT prompt,options_json,explanation,prompt_zh,options_zh_json FROM questions").fetchall()
        checked_questions = len(rows)
        for prompt, options, explanation, prompt_zh, options_zh in rows:
            private_strings.extend(value for value in (prompt, explanation, prompt_zh) if value)
            private_strings.extend(value for value in json.loads(options or "[]") + json.loads(options_zh or "[]") if len(value) >= 20)
    if checklist and checklist.is_file():
        items = json.loads(checklist.read_text(encoding="utf-8")).get("items", [])
        private_strings.extend(item[field] for item in items for field in ("title", "summary") if item.get(field))
    if any(value in text for value in private_strings for text in text_files):
        raise ValueError("Private question/checklist content in public output")
    return {**summary, "private_questions_checked": checked_questions}


def main() -> int:
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build")
    build.add_argument("--allowlist", type=Path, required=True)
    build.add_argument("--media-root", type=Path, required=True)
    build.add_argument("--output", type=Path, required=True)
    build.add_argument("--cache", type=Path, required=True)
    build.add_argument("--encoding", choices=("aac128", "copy"), default="aac128")
    audit = commands.add_parser("audit")
    audit.add_argument("--site", type=Path, required=True)
    audit.add_argument("--database", type=Path)
    audit.add_argument("--checklist", type=Path)
    args = parser.parse_args()
    if args.command == "build":
        result = build_bundle(args.allowlist, args.media_root, args.output, args.cache, encoding=args.encoding)
    else:
        result = audit_site(args.site, args.database, args.checklist)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
