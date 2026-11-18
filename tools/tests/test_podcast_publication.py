from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from podcast_publication import audit_site, build_bundle, validate_bundle, validate_catalog


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name)
        self.media = self.base / "private-media"
        self.media.mkdir()
        self.source = self.media / "synthetic.wav"
        with wave.open(str(self.source), "wb") as audio:
            audio.setparams((1, 2, 8000, 0, "NONE", "not compressed"))
            audio.writeframes(b"\0\0" * 8000)
        self.plan = {
            "schema_version": 1, "authorization": "user_requested_public_podcasts",
            "episodes": [{
                "id": "synthetic-1", "title": "Synthetic public title", "description": "Synthetic public description",
                "source_relative": "synthetic.wav",
                "source_sha256": hashlib.sha256(self.source.read_bytes()).hexdigest(),
                "published_at": "2026-11-18T00:00:00Z",
            }],
        }
        self.allowlist = self.base / "allowlist.json"
        self.output = self.base / "output"
        self.write_plan()
    def tearDown(self):
        self.temporary.cleanup()
    def write_plan(self):
        self.allowlist.write_text(json.dumps(self.plan))
    def build(self):
        return build_bundle(self.allowlist, self.media, self.output, self.base / "cache", encoding="copy")
    def public_shell(self):
        (self.output / "index.html").write_text("<main>Public player</main>")
        (self.output / "assets").mkdir()
        (self.output / "assets/app.js").write_text("console.log('public shell')")

    def test_export_is_explicit_and_does_not_include_source_metadata(self):
        summary = self.build()
        self.assertEqual(summary["episodes"], 1)
        manifest = (self.output / "episodes.json").read_text()
        self.assertNotIn("source_relative", manifest)
        self.assertNotIn("private-media", manifest)
        self.assertNotIn("authorization", manifest)
        self.assertEqual(validate_bundle(self.output), summary)
    def test_rejects_changed_source(self):
        self.source.write_bytes(self.source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "source changed"):
            self.build()
    def test_rejects_unapproved_plan(self):
        self.plan["authorization"] = "not-approved"
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "allowlist"):
            self.build()
    def test_rejects_parent_paths_and_escaping_symlinks(self):
        self.plan["episodes"][0]["source_relative"] = "../elsewhere.wav"
        self.write_plan()
        with self.assertRaises(ValueError):
            self.build()
        outside = self.base / "outside.wav"
        outside.write_bytes(self.source.read_bytes())
        (self.media / "escape.wav").symlink_to(outside)
        self.plan["episodes"][0]["source_relative"] = "escape.wav"
        self.write_plan()
        with self.assertRaisesRegex(ValueError, "escapes"):
            self.build()
    def test_rejects_extra_and_tampered_media(self):
        self.build()
        extra = self.output / "media/unlisted.wav"
        extra.write_bytes(self.source.read_bytes())
        with self.assertRaisesRegex(ValueError, "Unlisted"):
            validate_bundle(self.output)
        extra.unlink()
        audio = next((self.output / "media").iterdir())
        audio.write_bytes(audio.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "SHA-256"):
            validate_bundle(self.output)
    def test_catalog_rejects_private_fields_and_duplicate_ids(self):
        self.build()
        catalog = json.loads((self.output / "episodes.json").read_text())
        catalog["episodes"][0]["correct_answers"] = ["private"]
        with self.assertRaises(ValueError):
            validate_catalog(catalog)
        del catalog["episodes"][0]["correct_answers"]
        catalog["episodes"].append(catalog["episodes"][0])
        with self.assertRaises(ValueError):
            validate_catalog(catalog)
    def test_site_audit_rejects_database_and_credentials(self):
        self.build()
        self.public_shell()
        self.assertEqual(audit_site(self.output)["episodes"], 1)
        leaked = self.output / "learning.sqlite"
        leaked.write_bytes(b"SQLite format 3")
        with self.assertRaisesRegex(ValueError, "Unlisted"):
            audit_site(self.output)
        leaked.unlink()
        (self.output / "assets/app.js").write_text("github_pat_synthetic_credential")
        with self.assertRaisesRegex(ValueError, "Private content"):
            audit_site(self.output)
    def test_site_audit_reads_private_questions_without_exporting_them(self):
        self.build()
        self.public_shell()
        database = self.base / "private.sqlite"
        with sqlite3.connect(database) as db:
            db.execute("CREATE TABLE questions(prompt,options_json,explanation,prompt_zh,options_zh_json)")
            db.execute("INSERT INTO questions VALUES(?,?,?,?,?)", (
                "SYNTHETIC_PRIVATE_QUESTION_SENTINEL", "[]", None, None, "[]",
            ))
        self.assertEqual(audit_site(self.output, database)["private_questions_checked"], 1)
        (self.output / "assets/app.js").write_text("SYNTHETIC_PRIVATE_QUESTION_SENTINEL")
        with self.assertRaisesRegex(ValueError, "Private question"):
            audit_site(self.output, database)


if __name__ == "__main__":
    unittest.main()
