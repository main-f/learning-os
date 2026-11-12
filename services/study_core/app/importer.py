"""Read-only importer for the private MASO question bank.

The course checkout is treated as untrusted, read-only input. This module never
writes beneath ``COURSE_ROOT`` and never performs network requests.
"""

from __future__ import annotations

import hashlib
import html
from html.parser import HTMLParser
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import re
import unicodedata
import uuid

from .database import connect, get_db_path, initialize


COURSE_ID = "cyber-security"
FIRST_QUESTION_SET_ID = "cyber-security-exam1-speed-run"
RULESET_VERSION = "1"
QUESTION_SET_SIZE = 10
TOPIC_PATTERN = re.compile(r"^(?P<topic>[0-9]{2}-[0-9])_.+\.md$")
QUESTION_HEADING = re.compile(r"(?m)^## Q(?P<number>[0-9]+)\s*$")
OPTION_LINE = re.compile(r"^\s*1\.\s+(?P<text>.+?)\s*$")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", html.unescape(value))
    return re.sub(r"\s+", " ", value).strip()


def match_text(value: str) -> str:
    return normalize_text(value).casefold()


def question_content_hash(prompt: str, options: list[str]) -> str:
    canonical = json.dumps(
        {"prompt": normalize_text(prompt), "options": [normalize_text(x) for x in options]},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256_bytes(canonical)


@dataclass
class ImportedQuestion:
    question_id: str
    course_id: str
    topic_id: str
    local_question_number: int
    source_id: str
    source_ref: str
    source_sha256: str
    prompt: str
    options: list[str]
    content_hash: str
    markdown_answer_value: str | None = None
    learner_reasoning: str | None = None
    correct_options: list[int] = field(default_factory=list)
    answer_validation_status: str = "unverified"
    answer_source_ref: str | None = None


@dataclass
class TopicImport:
    topic_id: str
    source_id: str
    source_ref: str
    title: str
    source_sha256: str
    questions: list[ImportedQuestion]
    failures: list[str]


@dataclass
class HtmlQuestion:
    prompt: str
    options: list[str]
    answer_title: str
    source_ref: str


class SavedQuestionParser(HTMLParser):
    """Parse the saved MASO question list without executing page scripts."""

    def __init__(self, source_ref: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source_ref = source_ref
        self.questions: list[HtmlQuestion] = []
        self.current: dict[str, object] | None = None
        self.in_strong = False
        self.strong_chunks: list[str] = []
        self.ol_depth = 0
        self.in_option = False
        self.option_chunks: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        attr = {key: value or "" for key, value in attrs}
        if tag == "li" and "tehtavarivi" in attr.get("class", "").split():
            self.current = {
                "prompt": "",
                "options": [],
                "answer_title": attr.get("title", ""),
            }
            return
        if self.current is None:
            return
        if tag == "strong":
            self.in_strong = True
            self.strong_chunks = []
        elif tag == "ol":
            self.ol_depth += 1
        elif tag == "li" and self.ol_depth:
            self.in_option = True
            self.option_chunks = []

    def handle_data(self, data: str) -> None:
        if self.current is None:
            return
        if self.in_strong:
            self.strong_chunks.append(data)
        elif self.in_option:
            self.option_chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self.current is None:
            return
        if tag == "strong" and self.in_strong:
            self.current["prompt"] = normalize_text("".join(self.strong_chunks))
            self.in_strong = False
            return
        if tag == "li" and self.in_option:
            options = self.current["options"]
            assert isinstance(options, list)
            options.append(normalize_text("".join(self.option_chunks)))
            self.in_option = False
            return
        if tag == "ol" and self.ol_depth:
            self.ol_depth -= 1
            return
        if tag == "li" and not self.ol_depth:
            prompt = str(self.current["prompt"])
            options = list(self.current["options"])
            answer_title = str(self.current["answer_title"])
            if prompt or options or answer_title:
                self.questions.append(
                    HtmlQuestion(prompt, options, answer_title, self.source_ref)
                )
            self.current = None


def _answer_key(text: str, question_count: int) -> list[str | None]:
    match = re.search(
        r"(?ms)^## 答案\s*$\s*(.*?)(?=^#(?:[^#]|$)|\Z)", text
    )
    raw = normalize_text(match.group(1)) if match else ""
    compact = re.sub(r"\s+", "", raw)
    if len(compact) == question_count and all(char in "1234" for char in compact):
        return list(compact)
    return [None] * question_count


def parse_markdown_topic(
    path: Path, course_root: Path, course_id: str = COURSE_ID
) -> TopicImport:
    match = TOPIC_PATTERN.match(path.name)
    if not match:
        raise ValueError(f"Not a canonical topic file: {path.name}")
    raw = path.read_bytes()
    text = raw.decode("utf-8", errors="replace")
    topic_id = match.group("topic")
    source_id = f"{course_id}:{topic_id}"
    source_ref = path.relative_to(course_root).as_posix()
    source_sha = sha256_bytes(raw)
    title = next((normalize_text(line) for line in text.splitlines() if line.strip()), path.stem)
    headings = list(QUESTION_HEADING.finditer(text))
    answer_values = _answer_key(text, len(headings))
    questions: list[ImportedQuestion] = []
    failures: list[str] = []

    for index, heading in enumerate(headings):
        number = int(heading.group("number"))
        end = headings[index + 1].start() if index + 1 < len(headings) else len(text)
        answer_heading = re.search(r"(?m)^## 答案\s*$", text[heading.end() : end])
        if answer_heading:
            end = heading.end() + answer_heading.start()
        block = text[heading.end() : end].strip()
        reasoning_match = re.search(r"(?m)^### 思路和正确答案\s*$", block)
        question_part = block[: reasoning_match.start()] if reasoning_match else block
        reasoning = block[reasoning_match.end() :].strip() if reasoning_match else ""
        prompt_lines: list[str] = []
        options: list[str] = []
        for line in question_part.splitlines():
            option_match = OPTION_LINE.match(line)
            if option_match:
                options.append(normalize_text(option_match.group("text")))
            elif options and line.strip():
                options[-1] = normalize_text(f"{options[-1]} {line}")
            elif line.strip():
                prompt_lines.append(line)
        prompt = normalize_text(" ".join(prompt_lines))
        if not prompt or len(options) != 4:
            failures.append(
                f"{source_ref}#Q{number}: expected prompt and four ordered options"
            )
            continue
        content_hash = question_content_hash(prompt, options)
        questions.append(
            ImportedQuestion(
                question_id=f"{course_id}:{topic_id}:q{number}",
                course_id=course_id,
                topic_id=topic_id,
                local_question_number=number,
                source_id=source_id,
                source_ref=source_ref,
                source_sha256=source_sha,
                prompt=prompt,
                options=options,
                content_hash=content_hash,
                markdown_answer_value=answer_values[index],
                learner_reasoning=reasoning or None,
            )
        )

    return TopicImport(
        topic_id=topic_id,
        source_id=source_id,
        source_ref=source_ref,
        title=title,
        source_sha256=source_sha,
        questions=questions,
        failures=failures,
    )


def parse_saved_questions(path: Path, course_root: Path) -> list[HtmlQuestion]:
    source_ref = path.relative_to(course_root).as_posix()
    parser = SavedQuestionParser(source_ref)
    parser.feed(path.read_text(encoding="utf-8", errors="replace"))
    return parser.questions


def _safe_frame_path(main_page: Path, course_root: Path) -> Path:
    text = main_page.read_text(encoding="utf-8", errors="replace")
    match = re.search(
        r'<frame[^>]+name="fOheismateriaali"[^>]+src="([^"]+)"',
        text,
        flags=re.IGNORECASE,
    )
    if not match:
        raise ValueError(f"Missing fOheismateriaali frame: {main_page}")
    relative = html.unescape(match.group(1)).removeprefix("./")
    resolved = (main_page.parent / relative).resolve()
    if not resolved.is_relative_to(course_root):
        raise ValueError(f"Saved frame escapes COURSE_ROOT: {main_page}")
    if not resolved.is_file():
        raise ValueError(f"Saved question frame is missing: {resolved}")
    return resolved


def discover_saved_question_pages(course_root: Path) -> list[Path]:
    saved_root = course_root / "maso" / "0709" / "maso_html"
    if not saved_root.is_dir():
        return []
    pages = sorted(saved_root.glob("MASO _*.html"))
    return [_safe_frame_path(page, course_root) for page in pages]


def _validated_html_answer(question: HtmlQuestion) -> tuple[int | None, str | None]:
    match = re.match(r"^\s*([0-9]+)\.\s*(.*?)\s*$", question.answer_title, re.S)
    if not match:
        return None, "answer title has no numbered answer"
    answer_number = int(match.group(1))
    if answer_number < 1 or answer_number > len(question.options):
        return None, "answer number is outside the option range"
    title_answer = match_text(match.group(2))
    selected_answer = match_text(question.options[answer_number - 1])
    if not title_answer or title_answer != selected_answer:
        return None, "answer title text does not match its numbered option"
    return answer_number, None


def reconcile_questions(
    markdown_questions: list[ImportedQuestion], html_questions: list[HtmlQuestion]
) -> list[str]:
    """Mechanically reconcile prompt, ordered options, answer number and answer text."""

    failures: list[str] = []
    by_prompt: dict[str, list[ImportedQuestion]] = {}
    for question in markdown_questions:
        by_prompt.setdefault(match_text(question.prompt), []).append(question)

    matched_ids: set[str] = set()
    for html_question in html_questions:
        candidates = by_prompt.get(match_text(html_question.prompt), [])
        if len(candidates) != 1:
            failures.append(
                f"{html_question.source_ref}: prompt matched {len(candidates)} Markdown questions"
            )
            for candidate in candidates:
                candidate.answer_validation_status = "disputed"
                candidate.answer_source_ref = html_question.source_ref
            continue
        candidate = candidates[0]
        if candidate.question_id in matched_ids:
            candidate.answer_validation_status = "disputed"
            failures.append(f"{candidate.question_id}: matched more than one HTML answer")
            continue
        matched_ids.add(candidate.question_id)
        candidate.answer_source_ref = html_question.source_ref
        markdown_options = [match_text(value) for value in candidate.options]
        html_options = [match_text(value) for value in html_question.options]
        if len(html_options) != 4 or markdown_options != html_options:
            candidate.answer_validation_status = "disputed"
            continue
        answer_number, answer_error = _validated_html_answer(html_question)
        if answer_error or answer_number is None:
            candidate.answer_validation_status = "disputed"
            continue
        candidate.correct_options = [answer_number]
        candidate.answer_validation_status = "source_verified"
    return failures


def _question_sort_key(question: ImportedQuestion) -> tuple[str, int, str]:
    return (question.topic_id, question.local_question_number, question.question_id)


def _report_path(course_root: Path) -> Path:
    configured = os.getenv("LEARNING_OS_IMPORT_REPORT")
    path = (
        Path(configured).expanduser().resolve()
        if configured
        else get_db_path().parent / "import_report.json"
    )
    if path.resolve().is_relative_to(course_root):
        raise ValueError("Import report must not be written beneath COURSE_ROOT")
    return path


def import_course(course_root: str | None = None) -> dict[str, object]:
    started_at = now_iso()
    configured_root = course_root if course_root is not None else os.getenv("COURSE_ROOT", "")
    if not configured_root:
        raise ValueError("COURSE_ROOT is missing")
    root = Path(configured_root).expanduser().resolve()
    maso = root / "maso"
    if not maso.is_dir():
        raise ValueError(f"Expected folder absent: {maso}")
    if get_db_path().is_relative_to(root):
        raise ValueError("LEARNING_OS_DB must not be located beneath COURSE_ROOT")

    topic_paths = sorted(
        path for path in maso.iterdir() if path.is_file() and TOPIC_PATTERN.match(path.name)
    )
    topics = [parse_markdown_topic(path, root) for path in topic_paths]
    questions = [question for topic in topics for question in topic.questions]
    failures = [failure for topic in topics for failure in topic.failures]

    saved_question_pages = discover_saved_question_pages(root)
    html_questions: list[HtmlQuestion] = []
    for page in saved_question_pages:
        parsed = parse_saved_questions(page, root)
        if not parsed:
            failures.append(f"{page.relative_to(root).as_posix()}: no saved questions parsed")
        html_questions.extend(parsed)
    failures.extend(reconcile_questions(questions, html_questions))

    by_hash: dict[str, list[ImportedQuestion]] = {}
    for question in questions:
        by_hash.setdefault(question.content_hash, []).append(question)
    duplicate_count = sum(max(0, len(items) - 1) for items in by_hash.values())
    verified = sorted(
        (
            question
            for question in questions
            if question.answer_validation_status == "source_verified"
            and question.correct_options
        ),
        key=_question_sort_key,
    )
    selected = verified[:QUESTION_SET_SIZE]
    selected_ids = [question.question_id for question in selected]
    set_digest = sha256_bytes(
        json.dumps(
            [(question.question_id, question.content_hash) for question in selected],
            separators=(",", ":"),
        ).encode("utf-8")
    )[:12]
    set_version = f"1.{set_digest}" if len(selected) == QUESTION_SET_SIZE else None
    imported_at = now_iso()
    report_path = _report_path(root)
    source_paths = [topic.source_ref for topic in topics] + [
        path.relative_to(root).as_posix() for path in saved_question_pages
    ]
    report: dict[str, object] = {
        "topic_count": len(topics),
        "candidate_question_count": len(questions),
        "source_verified_count": len(verified),
        "duplicate_count": duplicate_count,
        "disputed_count": sum(
            question.answer_validation_status == "disputed" for question in questions
        ),
        "failed_count": len(failures),
        "selected_question_ids": selected_ids,
        "source_paths": source_paths,
        "question_set_id": FIRST_QUESTION_SET_ID if set_version else None,
        "question_set_version": set_version,
        "ruleset_version": RULESET_VERSION,
        "imported_at": imported_at,
    }

    initialize()
    with connect() as db:
        for topic in topics:
            db.execute(
                """INSERT INTO course_sources
                    (source_id,relative_path,title,sha256,content_hash,source_type,imported_at)
                    VALUES(?,?,?,?,?,'personal_notes',?)
                    ON CONFLICT(source_id) DO UPDATE SET
                        relative_path=excluded.relative_path,
                        title=excluded.title,
                        sha256=excluded.sha256,
                        content_hash=excluded.content_hash,
                        imported_at=excluded.imported_at""",
                (
                    topic.source_id,
                    topic.source_ref,
                    topic.title,
                    topic.source_sha256,
                    topic.source_sha256,
                    imported_at,
                ),
            )
        for question in questions:
            db.execute(
                """INSERT INTO questions(
                    question_id,course_id,topic_id,local_question_number,source_id,
                    source_ref,answer_source_ref,source_sha256,question_type,prompt,
                    options_json,correct_options_json,answer_validation_status,
                    distribution_scope,explanation,explanation_status,
                    markdown_answer_value,learner_reasoning,content_hash,version,
                    imported_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,'single_choice',?,?,?,?,
                           'private_only',NULL,'pending_human_review',?,?,?,?,?,?)
                    ON CONFLICT(question_id) DO UPDATE SET
                        source_id=excluded.source_id,
                        source_ref=excluded.source_ref,
                        answer_source_ref=excluded.answer_source_ref,
                        source_sha256=excluded.source_sha256,
                        question_type=excluded.question_type,
                        prompt=excluded.prompt,
                        options_json=excluded.options_json,
                        correct_options_json=excluded.correct_options_json,
                        answer_validation_status=excluded.answer_validation_status,
                        distribution_scope=excluded.distribution_scope,
                        explanation=NULL,
                        explanation_status='pending_human_review',
                        markdown_answer_value=excluded.markdown_answer_value,
                        learner_reasoning=excluded.learner_reasoning,
                        content_hash=excluded.content_hash,
                        version=excluded.version,
                        imported_at=excluded.imported_at,
                        updated_at=excluded.updated_at""",
                (
                    question.question_id,
                    question.course_id,
                    question.topic_id,
                    question.local_question_number,
                    question.source_id,
                    question.source_ref,
                    question.answer_source_ref,
                    question.source_sha256,
                    question.prompt,
                    json.dumps(question.options, ensure_ascii=False),
                    json.dumps(question.correct_options),
                    question.answer_validation_status,
                    question.markdown_answer_value,
                    question.learner_reasoning,
                    question.content_hash,
                    question.content_hash[:16],
                    imported_at,
                    imported_at,
                ),
            )
        if set_version:
            db.execute(
                """INSERT INTO question_sets(
                    question_set_id,version,ruleset_version,question_ids_json,
                    created_at,private_only)
                    VALUES(?,?,?,?,?,1)
                    ON CONFLICT(question_set_id,version) DO UPDATE SET
                        ruleset_version=excluded.ruleset_version,
                        question_ids_json=excluded.question_ids_json,
                        created_at=excluded.created_at,
                        private_only=1""",
                (
                    FIRST_QUESTION_SET_ID,
                    set_version,
                    RULESET_VERSION,
                    json.dumps(selected_ids),
                    imported_at,
                ),
            )

    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_report = report_path.with_suffix(report_path.suffix + ".tmp")
    temporary_report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary_report.replace(report_path)

    completed_at = now_iso()
    import_id = str(uuid.uuid4())
    with connect() as db:
        db.execute(
            """INSERT INTO import_runs(
                import_id,course_root,topic_count,candidate_question_count,
                source_verified_count,duplicate_count,disputed_count,failed_count,
                selected_question_ids_json,source_paths_json,report_path,
                started_at,completed_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                import_id,
                str(root),
                report["topic_count"],
                report["candidate_question_count"],
                report["source_verified_count"],
                report["duplicate_count"],
                report["disputed_count"],
                report["failed_count"],
                json.dumps(selected_ids),
                json.dumps(source_paths),
                str(report_path),
                started_at,
                completed_at,
            ),
        )

    return {**report, "import_id": import_id, "report_path": str(report_path)}


def import_topics(course_root: str | None = None) -> dict[str, object]:
    """Backward-compatible command name for the full private import."""

    return import_course(course_root)
