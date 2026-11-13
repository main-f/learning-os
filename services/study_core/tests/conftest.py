from __future__ import annotations

from dataclasses import dataclass
import html
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.importer import import_course
from app.main import app


@dataclass
class SyntheticCourse:
    root: Path
    correct_by_id: dict[str, int]
    prompts_by_id: dict[str, str]
    options_by_id: dict[str, list[str]]


def build_synthetic_course(root: Path, disputed_question_id: str | None = None) -> SyntheticCourse:
    maso = root / "maso"
    saved = maso / "0709" / "maso_html"
    saved.mkdir(parents=True)
    correct_by_id: dict[str, int] = {}
    prompts_by_id: dict[str, str] = {}
    options_by_id: dict[str, list[str]] = {}
    global_index = 0

    def topic(topic_id: str, count: int, with_html: bool) -> None:
        nonlocal global_index
        markdown = [f"Synthetic > Topic >> {topic_id}", "# 笔记区", "Synthetic notes", "", "# MCQ区"]
        html_questions: list[str] = []
        for number in range(1, count + 1):
            question_id = f"cyber-security:{topic_id}:q{number}"
            prompt = f"Synthetic prompt {topic_id}-{number}?"
            options = [f"Synthetic choice {topic_id}-{number}-{letter}" for letter in "ABCD"]
            correct = global_index % 4 + 1
            global_index += 1
            correct_by_id[question_id] = correct
            prompts_by_id[question_id] = prompt
            options_by_id[question_id] = options
            markdown.extend(
                [
                    f"## Q{number}",
                    prompt,
                    *[f"1. {option}" for option in options],
                    "### 思路和正确答案",
                    "我选了____，这是合成测试推理，不是正式答案。",
                    "",
                ]
            )
            if with_html:
                title_text = options[correct - 1]
                if question_id == disputed_question_id:
                    title_text = "Synthetic mismatched answer title"
                html_questions.append(
                    '<li class="tehtavarivi" title="'
                    + html.escape(f"{correct}. {title_text}", quote=True)
                    + '"><strong>'
                    + html.escape(prompt)
                    + "</strong><ol>"
                    + "".join(f"<li>{html.escape(option)}</li>" for option in options)
                    + "</ol></li>"
                )
        markdown.extend(["## 答案", "", "# 贡献区", ""])
        (maso / f"{topic_id}_synthetic.md").write_text("\n".join(markdown), encoding="utf-8")
        if with_html:
            page_title = f"Synthetic {topic_id}"
            files_dir = saved / f"MASO _ {page_title}_files"
            files_dir.mkdir()
            question_page = files_dir / "oheismateriaali.html"
            question_page.write_text(
                "<!doctype html><html><body><ul>" + "".join(html_questions) + "</ul></body></html>",
                encoding="utf-8",
            )
            (saved / f"MASO _ {page_title}.html").write_text(
                '<!doctype html><frameset><frame name="fOheismateriaali" '
                f'src="./MASO _ {page_title}_files/oheismateriaali.html"></frameset>',
                encoding="utf-8",
            )

    topic("01-1", 5, True)
    topic("01-2", 6, True)
    topic("01-3", 1, False)
    return SyntheticCourse(root, correct_by_id, prompts_by_id, options_by_id)


@pytest.fixture
def course_factory(tmp_path: Path):
    sequence = 0

    def factory(disputed_question_id: str | None = None) -> SyntheticCourse:
        nonlocal sequence
        sequence += 1
        return build_synthetic_course(tmp_path / f"course-{sequence}", disputed_question_id)

    return factory


@pytest.fixture
def synthetic_course(course_factory) -> SyntheticCourse:
    return course_factory()


@pytest.fixture
def imported_course(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, synthetic_course: SyntheticCourse):
    database = tmp_path / "private" / "learning.sqlite"
    report = tmp_path / "private" / "import_report.json"
    monkeypatch.setenv("LEARNING_OS_DB", str(database))
    monkeypatch.setenv("LEARNING_OS_IMPORT_REPORT", str(report))
    result = import_course(str(synthetic_course.root))
    return synthetic_course, database, report, result


@pytest.fixture
def api_client(imported_course):
    course, database, report, result = imported_course
    with TestClient(app) as client:
        yield client, course, database, report, result

