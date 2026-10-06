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
    lines = _lines(10, chars=30)
    lines[0] = sr.ReviewLine(id="l0", text="「もう少しで落ちそうになったよ」".ljust(30, "あ"), timestamp=0.0)
    result = gen.run(lines, "Game", progress=lambda s, d: stages.append((s, d)), question_count=12)

    kinds = [k for k, _, _ in ai.calls]
    assert kinds.count("session_review_digest") == 4
    assert kinds.count("session_review_merge") == 1
    assert kinds.count("session_review_quiz") == 2  # 8 + 4
    assert [s for s, _ in stages[:4]] == ["digest"] * 4 and ("merge", "") in stages
    assert ("quiz", "0/12") in stages and ("quiz", "8/12") in stages

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


# --- consistency pass ---------------------------------------------------------


def _hl(line_id, quote):
    return sr.Highlight(line_id=line_id, quote=quote, construction="c")


def _q(qid, sources):
    return sr.QuizQuestion(id=qid, kind="events", question_ja="質問", source_line_ids=sources)


CONSISTENCY_LINES = [
    sr.ReviewLine(id="a", text="「もう少しで落ちそうになったよ」"),
    sr.ReviewLine(id="b", text="別に、心配してたわけじゃないけど。"),
]


def test_consistency_keeps_real_quotes_and_repairs_wrong_line_ids():
    highlights, quiz, notes = sr.check_consistency(
        [_hl("a", "落ちそうになった"), _hl("a", "心配してたわけじゃない"), _hl("zzz", "「別に、心配してた…」")],
        [],
        CONSISTENCY_LINES,
    )
    assert [(h.line_id, h.quote) for h in highlights] == [
        ("a", "落ちそうになった"),
        ("b", "心配してたわけじゃない"),
        ("b", "「別に、心配してた…」"),
    ]
    assert notes["highlights_relinked"] == 2 and notes["highlights_dropped"] == 0


def test_consistency_drops_invented_quotes():
    highlights, _, notes = sr.check_consistency([_hl("a", "空を飛んだ"), _hl("a", "")], [], CONSISTENCY_LINES)
    assert highlights == [] and notes["highlights_dropped"] == 2


def test_consistency_filters_quiz_sources():
    _, quiz, notes = sr.check_consistency(
        [],
        [_q("q1", ["a", "x"]), _q("q2", ["x", "y"]), _q("q3", [])],
        CONSISTENCY_LINES,
    )
    assert [(q.id, q.source_line_ids) for q in quiz] == [("q1", ["a"]), ("q3", [])]
    assert notes["questions_dropped"] == 1


def test_consistency_never_drops_every_question():
    _, quiz, notes = sr.check_consistency([], [_q("q1", ["x"]), _q("q2", ["y"])], CONSISTENCY_LINES)
    assert [(q.id, q.source_line_ids) for q in quiz] == [("q1", []), ("q2", [])]
    assert notes["questions_dropped"] == 0


def test_run_applies_the_consistency_pass():
    ai = _FakeAI()
    gen = sr.SessionReviewGenerator(ai, native_language="English")
    # Lines without the quoted phrase: the fake model's highlight is invented and must go.
    result = gen.run(_lines(5, chars=30), "Game", question_count=2)
    assert result.highlights == []
    assert len(result.quiz) == 2 and result.quiz[0].source_line_ids == ["l0"]


class _ScriptedAI:
    """Returns one canned JSON reply and records the prompt."""

    def __init__(self, reply: dict):
        self.reply = reply
        self.prompts = []

    def generate_raw_prompt(self, prompt, request_kind="raw", max_tokens=None):
        self.prompts.append((request_kind, prompt))
        return json.dumps(self.reply, ensure_ascii=False)


_Q4 = sr.QuizQuestion(
    id="q1-4",
    kind="register",
    question_ja="「分からないことは何でも聞いたね！」という言い方から、どんな雰囲気が伝わりますか？",
    source_line_ids=["l1"],
)
_LINES = [
    sr.ReviewLine(id="l0", text="新学期の授業を始めます"),
    sr.ReviewLine(id="l1", text="分からないことは何でも聞いたね！"),
]


def test_grade_keeps_score_inside_the_verdict_band_and_answers_the_learners_question():
    ai = _ScriptedAI(
        {
            "verdict": "incorrect",
            "score": 60,
            "feedback_ja": "f",
            "feedback_en": "f",
            "japanese_fixes": [
                {"original": "楽な雰囲気", "fixed": "気楽な雰囲気", "note_en": "more natural"},
                {"original": "not in the answer", "fixed": "x", "note_en": "invented"},
                {"original": "伝わっている", "fixed": "伝わっている", "note_en": "no change"},
            ],
            "model_answer_ja": "m",
            "reply_ja": "「聞いたね」は字幕の誤りで、「聞いてね」だと思います。",
            "reply_en": "Probably a subtitle error for 聞いてね.",
        }
    )
    grade = sr.SessionReviewGenerator(ai).grade_answer(
        _Q4, "楽な雰囲気が伝わっている。「何でも聞いたね」の文法を説明してください。", _LINES, "Azumanga Daioh"
    )
    assert (grade.verdict, grade.score) == ("incorrect", 29)
    assert [f["original"] for f in grade.japanese_fixes] == ["楽な雰囲気"]
    assert grade.reply_ja.startswith("「聞いたね」")
    prompt = ai.prompts[0][1]
    assert "mis-transcribed" in prompt and "reply_ja" in prompt and "[l0]" in prompt


@pytest.mark.parametrize(
    ("verdict", "score", "expected"),
    [
        ("correct", 50, ("correct", 80)),
        ("partial", 20, ("partial", 30)),
        ("partial", 95, ("partial", 79)),
        ("odd", 40, ("partial", 40)),
    ],
)
def test_grade_score_bands(verdict, score, expected):
    ai = _ScriptedAI({"verdict": verdict, "score": score})
    assert (lambda g: (g.verdict, g.score))(
        sr.SessionReviewGenerator(ai).grade_answer(_Q4, "答え", _LINES, "G")
    ) == expected


def test_discuss_can_revise_the_grade():
    ai = _ScriptedAI(
        {
            "reply_ja": "その通りです。字幕の誤りでした。",
            "reply_en": "You're right; it was a subtitle error.",
            "revised": {"verdict": "partial", "score": 90, "feedback_ja": "直しました", "feedback_en": "revised"},
        }
    )
    result = sr.SessionReviewGenerator(ai).discuss_grade(
        _Q4,
        "楽な雰囲気",
        {"verdict": "incorrect", "score": 20, "feedback_ja": "x", "discussion": [{"secret": "not sent"}]},
        [{"message": "前の質問", "reply_ja": "前の回答"}],
        "「聞いたね」は字幕の誤りでは？",
        _LINES,
        "Azumanga Daioh",
    )
    assert result["revised"] == {
        "verdict": "partial",
        "score": 79,
        "feedback_ja": "直しました",
        "feedback_en": "revised",
    }
    kind, prompt = ai.prompts[0]
    assert kind == "session_review_discuss"
    assert "「聞いたね」は字幕の誤りでは？" in prompt and "前の質問" in prompt and "not sent" not in prompt


def test_discuss_keeps_the_grade_when_it_stands_and_needs_a_message():
    ai = _ScriptedAI({"reply_ja": "採点は妥当です。", "reply_en": "The grade stands.", "revised": None})
    gen = sr.SessionReviewGenerator(ai)
    assert gen.discuss_grade(_Q4, "a", {}, [], "なぜ？", _LINES, "G")["revised"] is None
    with pytest.raises(ValueError):
        gen.discuss_grade(_Q4, "a", {}, [], "  ", _LINES, "G")
