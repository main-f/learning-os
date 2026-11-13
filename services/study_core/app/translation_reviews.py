"""Import a private Chinese translation review pack into Study Core.

The pack lives under gitignored ``data/reviews``. Draft text is useful for human
review but gameplay returns it only after an explicit, attributable approval.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .database import connect, initialize


def apply_translation_review_pack(path: Path) -> dict[str, int]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema_version") != 1 or not isinstance(payload.get("questions"), list):
        raise ValueError("Unsupported translation review pack")

    counts = {"draft": 0, "human_verified": 0, "disputed": 0}
    initialize()
    with connect() as db:
        for entry in payload["questions"]:
            question_id = entry.get("question_id")
            question = db.execute(
                """SELECT * FROM questions WHERE question_id=?
                   AND answer_validation_status='source_verified'
                   AND distribution_scope='private_only'""",
                (question_id,),
            ).fetchone()
            if question is None:
                raise ValueError(f"Unknown or ineligible question: {question_id}")
            if entry.get("content_hash") != question["content_hash"]:
                raise ValueError(f"Stale translation source for {question_id}")
            if entry.get("prompt_en") != question["prompt"]:
                raise ValueError(f"English prompt mismatch for {question_id}")
            options_en = json.loads(question["options_json"])
            if entry.get("options_en") != options_en:
                raise ValueError(f"English options mismatch for {question_id}")
            prompt_zh = entry.get("prompt_zh")
            options_zh = entry.get("options_zh")
            if not isinstance(prompt_zh, str) or not prompt_zh.strip():
                raise ValueError(f"Missing Chinese prompt draft for {question_id}")
            if (
                not isinstance(options_zh, list)
                or len(options_zh) != len(options_en)
                or any(not isinstance(item, str) or not item.strip() for item in options_zh)
            ):
                raise ValueError(f"Invalid Chinese option drafts for {question_id}")
            if not isinstance(entry.get("key_terms"), list) or not isinstance(
                entry.get("translation_risks"), list
            ):
                raise ValueError(f"Review notes are missing for {question_id}")
            review = entry.get("review") or {}
            approved = review.get("approve") is True
            disputed = review.get("dispute") is True
            if approved and disputed:
                raise ValueError(f"Review cannot approve and dispute {question_id}")
            reviewed_at = review.get("reviewed_at")
            reviewer = review.get("reviewer")
            human_verified = bool(approved and not disputed and reviewed_at and reviewer)
            status = "human_verified" if human_verified else "draft"
            if disputed:
                counts["disputed"] += 1
            counts[status] += 1
            db.execute(
                """UPDATE questions SET prompt_zh=?,options_zh_json=?,
                   translation_status=?,translation_version=?,translation_reviewed_at=?,
                   updated_at=CASE WHEN ? IS NOT NULL THEN ? ELSE updated_at END
                   WHERE question_id=?""",
                (
                    prompt_zh.strip(),
                    json.dumps(options_zh, ensure_ascii=False),
                    status,
                    payload.get("translation_version") or "zh-draft-v1",
                    reviewed_at if human_verified else None,
                    reviewed_at if human_verified else None,
                    reviewed_at,
                    question_id,
                ),
            )
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply a private translation review pack")
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    print(json.dumps(apply_translation_review_pack(args.path), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
