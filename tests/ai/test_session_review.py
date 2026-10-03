from __future__ import annotations

import json

import pytest

from GameSentenceMiner.ai.features import session_review as sr
from GameSentenceMiner.ai.prompts import session_review as prompts


def _lines(n: int, chars: int = 20) -> list[sr.ReviewLine]:
    return [sr.ReviewLine(id=f"l{i}", text="あ" * chars, timestamp=float(i)) for i in range(n)]


# --- pure helpers -----------------------------------------------------------


def test_parse_json_object_tolerates_fences_and_prose():
    raw = 'Sure! ```json\n{"summary_ja": "x", "n": 1}\n```\nHope that helps.'
    assert sr.parse_json_object(raw) == {"summary_ja": "x", "n": 1}


@pytest.mark.parametrize("raw", ["", "no json here", "[1,2]", "Processing failed: boom"])
def test_parse_json_object_rejects_bad_output(raw):
    with pytest.raises(sr.SessionReviewError):
        sr.parse_json_object(raw)


def test_chunk_lines_respects_char_budget_and_order():
    chunks = sr.chunk_lines(_lines(10, chars=30), max_chars=100)
    assert [len(c) for c in chunks] == [3, 3, 3, 1]
    assert [ln.id for c in chunks for ln in c] == [f"l{i}" for i in range(10)]


def test_chunk_lines_keeps_oversized_line_alone():
    big = sr.ReviewLine(id="big", text="あ" * 500)
    chunks = sr.chunk_lines([sr.ReviewLine(id="a", text="い"), big, sr.ReviewLine(id="b", text="う")], max_chars=100)
    assert [[ln.id for ln in c] for c in chunks] == [["a"], ["big"], ["b"]]


@pytest.mark.parametrize(
    "chars,expected",
    [(0, 0), (1, sr.QUIZ_MIN_QUESTIONS), (12_000, 10), (10**7, sr.QUIZ_MAX_QUESTIONS)],
)
def test_quiz_question_count_scales_with_characters(chars, expected):
    assert sr.quiz_question_count(chars) == expected


def test_prompt_render_keeps_json_braces_and_dialogue_braces():
    text = prompts.render(
        prompts.GRADE_PROMPT,
        **prompts.common_values("English"),
        game_title="G",
        question='{"id": "q1"}',
        source_lines="[l1] {笑}",
        answer="はい",
    )
    assert '"verdict": "correct|partial|incorrect"' in text
    assert "[l1] {笑}" in text
    assert "{native_language}" not in text and "{data_guard}" not in text


# --- pipeline with a fake AI ------------------------------------------------


class _FakeAI:
    """Answers by request_kind; records prompts so tests can assert on their content."""

    def __init__(self):
        self.calls: list[tuple[str, str, int]] = []

    def generate_raw_prompt(self, prompt, request_kind="raw", max_tokens=None):
        self.calls.append((request_kind, prompt, max_tokens))
        if request_kind == "session_review_digest":
            return json.dumps(
                {
                    "summary_ja": "要約",
                    "events_ja": ["出来事"],
                    "speakers": [{"name": "A", "attitude_ja": "強気"}],
                    "candidates": [
                        {
                            "line_id": "l0",
                            "quote": "落ちそうになった",
                            "construction": "〜そうになる",
                            "naive_reading_ja": "落ちるように見えた",
                            "naive_reading_en": "looked like it would fall",
                            "correct_reading_ja": "もう少しで落ちた",
                            "correct_reading_en": "almost fell",
                            "why_it_matters_en": "it did not fall",
                            "category": "aspect_modality",
                        }
                    ],
                }
            )
        if request_kind == "session_review_merge":
            return json.dumps(
                {
                    "summary_ja": "全体の要約",
                    "summary_en": "Overall summary",
                    "characters": [{"name": "A", "attitude_ja": "強気", "attitude_en": "assertive"}],
                    "highlights": [
                        {
                            "line_id": "l0",
                            "quote": "落ちそうになった",
                            "construction": "〜そうになる",
                            "naive_reading_ja": "x",
                            "naive_reading_en": "y",
                            "correct_reading_ja": "z",
                            "correct_reading_en": "w",
                            "why_it_matters_en": "v",
                            "category": "aspect_modality",
                            "confidence": "0.9",
                        }
                    ],
                    "may_have_missed_ja": ["点"],
                    "may_have_missed_en": ["point"],
                }
            )
        if request_kind == "session_review_quiz":
            n = int(prompt.split("Write ")[1].split(" questions")[0])
            prefix = prompt.split('ids must be "')[1].split('1"')[0]
            return json.dumps(
                {
                    "questions": [
                        {
                            "id": f"{prefix}{i + 1}",
                            "kind": "events",
                            "question_ja": f"質問{prefix}{i + 1}",
                            "reference_answer_ja": "答え",
                            "rubric_en": ["fact"],
                            "source_line_ids": ["l0"],
                        }
                        for i in range(n)
                    ]
                }
            )
        if request_kind == "session_review_grade":
            return json.dumps(
                {
                    "verdict": "partial",
                    "score": "65.4",
                    "feedback_ja": "惜しい",
                    "feedback_en": "close",
                    "japanese_fixes": [{"original": "落ちた", "fixed": "落ちそうになった", "note_en": "aspect"}],
                    "model_answer_ja": "模範",
                }
            )
        raise AssertionError(request_kind)


def test_run_chunks_merges_and_batches_quiz():
    ai = _FakeAI()
    gen = sr.SessionReviewGenerator(ai, native_language="English", chunk_chars=100)
    stages = []
    result = gen.run(_lines(10, chars=30), "Game", progress=lambda s, d: stages.append(s), question_count=12)

    kinds = [k for k, _, _ in ai.calls]
    assert kinds.count("session_review_digest") == 4
    assert kinds.count("session_review_merge") == 1
    assert kinds.count("session_review_quiz") == 2  # 8 + 4
    assert stages[:4] == ["digest"] * 4 and "merge" in stages and "quiz" in stages

    assert result.summary_ja == "全体の要約" and result.summary_en == "Overall summary"
    assert result.highlights[0].confidence == 0.9 and result.highlights[0].category == "aspect_modality"
    assert [q.id for q in result.quiz] == [f"q1-{i}" for i in range(1, 9)] + [f"q2-{i}" for i in range(1, 5)]
    assert result.char_count == 300 and result.line_count == 10

    second_quiz_prompt = [p for k, p, _ in ai.calls if k == "session_review_quiz"][1]
    assert "質問q1-1" in second_quiz_prompt  # later batches see earlier questions

    digest_prompt = next(p for k, p, _ in ai.calls if k == "session_review_digest")
    assert "[l0] " in digest_prompt and "chunk 1 of 4" in digest_prompt
    assert all(mt for _, _, mt in ai.calls)  # every stage overrides max_tokens


def test_run_uses_character_based_question_count_by_default():
    ai = _FakeAI()
    gen = sr.SessionReviewGenerator(ai, native_language="English")
    result = gen.run(_lines(100, chars=60), "Game")  # 6000 chars -> 5 questions
    assert len(result.quiz) == 5


def test_run_rejects_empty_session():
    with pytest.raises(sr.SessionReviewError):
        sr.SessionReviewGenerator(_FakeAI()).run([sr.ReviewLine(id="a", text="  ")], "Game")


def test_grade_answer_normalizes_fields():
    gen = sr.SessionReviewGenerator(_FakeAI())
    q = sr.QuizQuestion(id="q1-1", kind="events", question_ja="何が起きた？", source_line_ids=["l0"])
    grade = gen.grade_answer(q, "落ちた", [sr.ReviewLine(id="l0", text="落ちそうになった")], "Game")
    assert grade.verdict == "partial" and grade.score == 65
    assert grade.japanese_fixes[0]["fixed"] == "落ちそうになった"


def test_grade_answer_requires_text():
    with pytest.raises(ValueError):
        sr.SessionReviewGenerator(_FakeAI()).grade_answer(
            sr.QuizQuestion(id="q", kind="k", question_ja="?"), "  ", [], "G"
        )


def test_call_retries_once_on_unparseable_output():
    class Flaky:
        def __init__(self):
            self.n = 0

        def generate_raw_prompt(self, prompt, request_kind="raw", max_tokens=None):
            self.n += 1
            return "garbage" if self.n == 1 else '{"ok": true}'

    gen = sr.SessionReviewGenerator(Flaky())
    assert gen._call("p", "k", 10) == {"ok": True}


def test_call_gives_up_after_retry():
    class Broken:
        def generate_raw_prompt(self, prompt, request_kind="raw", max_tokens=None):
            return "still garbage"

    with pytest.raises(sr.SessionReviewError):
        sr.SessionReviewGenerator(Broken())._call("p", "k", 10)
