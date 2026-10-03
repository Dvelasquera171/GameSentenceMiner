"""Session comprehension review: summary (JA/EN), silent-misreading highlights, quiz, grading.

Pipeline (each step is one or more AI calls; generation is offline, grading is live):

    lines ──chunk──▶ digest_chunk ×N ──▶ merge_digests ──▶ generate_quiz (batched) ──▶ SessionReviewResult
    (later) grade_answer(question, user_answer_ja) ──▶ QuizGrade

The generator only depends on an object exposing ``generate_raw_prompt(prompt, request_kind,
max_tokens)`` (``AIService``), so tests inject a fake. Everything the model returns is parsed
through ``parse_json_object`` which tolerates fences and leading/trailing prose.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass, field
from typing import Callable, Iterable, List, Optional, Sequence

from GameSentenceMiner.ai.prompts import session_review as prompts

# Tuning knobs. Chunk size is in characters of Japanese text (roughly 1 token per 1-2 chars).
DEFAULT_CHUNK_CHARS = 6000
MAX_CANDIDATES_PER_CHUNK = 6
MAX_HIGHLIGHTS = 12
QUIZ_CHARS_PER_QUESTION = 1200
QUIZ_MIN_QUESTIONS = 4
QUIZ_MAX_QUESTIONS = 30
QUIZ_BATCH_SIZE = 8
QUIZ_FULL_DIALOGUE_MAX_CHARS = 20000
DIGEST_MAX_TOKENS = 4096
MERGE_MAX_TOKENS = 8192
QUIZ_MAX_TOKENS = 8192
GRADE_MAX_TOKENS = 2048

ProgressCallback = Callable[[str, str], None]


class SessionReviewError(Exception):
    pass


@dataclass
class ReviewLine:
    id: str
    text: str
    timestamp: float = 0.0
    speaker: str = ""

    @classmethod
    def from_game_line(cls, line) -> "ReviewLine":
        # Accepts GameLinesTable rows (line_text) and in-memory GameLine objects (text).
        text = getattr(line, "line_text", None)
        if text is None:
            text = getattr(line, "text", "")
        return cls(
            id=str(getattr(line, "id", "")),
            text=str(text or ""),
            timestamp=float(getattr(line, "timestamp", 0.0) or 0.0),
            speaker=str(getattr(line, "speaker", "") or ""),
        )


@dataclass
class Highlight:
    line_id: str = ""
    quote: str = ""
    construction: str = ""
    naive_reading_ja: str = ""
    naive_reading_en: str = ""
    correct_reading_ja: str = ""
    correct_reading_en: str = ""
    why_it_matters_en: str = ""
    category: str = "other"
    confidence: float = 0.0


@dataclass
class QuizQuestion:
    id: str
    kind: str
    question_ja: str
    hint_ja: str = ""
    reference_answer_ja: str = ""
    reference_answer_en: str = ""
    rubric_en: List[str] = field(default_factory=list)
    source_line_ids: List[str] = field(default_factory=list)


@dataclass
class QuizGrade:
    verdict: str
    score: int
    feedback_ja: str = ""
    feedback_en: str = ""
    japanese_fixes: List[dict] = field(default_factory=list)
    model_answer_ja: str = ""


@dataclass
class SessionReviewResult:
    summary_ja: str
    summary_en: str
    characters: List[dict]
    highlights: List[Highlight]
    may_have_missed_ja: List[str]
    may_have_missed_en: List[str]
    quiz: List[QuizQuestion]
    digests: List[dict]
    line_count: int
    char_count: int

    def to_dict(self) -> dict:
        data = asdict(self)
        data.pop("digests", None)
        return data


# ---------------------------------------------------------------------------
# Pure helpers (unit-tested, no AI)
# ---------------------------------------------------------------------------


def parse_json_object(raw: str) -> dict:
    """Extract the first top-level JSON object from model output. Raises SessionReviewError."""
    if not raw or not isinstance(raw, str):
        raise SessionReviewError("Empty AI response")
    text = raw.strip()
    if text.startswith("Processing failed:"):
        raise SessionReviewError(text)
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.MULTILINE).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise SessionReviewError("AI response contained no JSON object")
    try:
        parsed = json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise SessionReviewError(f"AI response was not valid JSON: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SessionReviewError("AI response JSON was not an object")
    return parsed


def chunk_lines(lines: Sequence[ReviewLine], max_chars: int = DEFAULT_CHUNK_CHARS) -> List[List[ReviewLine]]:
    """Split in reading order into chunks of at most ``max_chars`` (a single long line is its own chunk)."""
    chunks: List[List[ReviewLine]] = []
    current: List[ReviewLine] = []
    size = 0
    for line in lines:
        length = len(line.text)
        if current and size + length > max_chars:
            chunks.append(current)
            current, size = [], 0
        current.append(line)
        size += length
    if current:
        chunks.append(current)
    return chunks


def quiz_question_count(char_count: int) -> int:
    """Quiz length scales with characters read, not time: ~1 question per 1200 chars, clamped."""
    if char_count <= 0:
        return 0
    return max(QUIZ_MIN_QUESTIONS, min(QUIZ_MAX_QUESTIONS, math.ceil(char_count / QUIZ_CHARS_PER_QUESTION)))


def format_dialogue(lines: Iterable[ReviewLine]) -> str:
    return "\n".join(
        prompts.LINE_FORMAT.format(id=ln.id, speaker=f"{ln.speaker}: " if ln.speaker else "", text=ln.text)
        for ln in lines
    )


def _as_list(value) -> list:
    return value if isinstance(value, list) else []


def _highlight_from_dict(data: dict) -> Highlight:
    fields = {k: v for k, v in data.items() if k in Highlight.__dataclass_fields__}
    try:
        fields["confidence"] = float(fields.get("confidence", 0.0) or 0.0)
    except (TypeError, ValueError):
        fields["confidence"] = 0.0
    return Highlight(**{k: (v if v is not None else "") for k, v in fields.items()})


def _question_from_dict(data: dict, fallback_id: str) -> Optional[QuizQuestion]:
    question = str(data.get("question_ja") or "").strip()
    if not question:
        return None
    return QuizQuestion(
        id=str(data.get("id") or fallback_id),
        kind=str(data.get("kind") or "events"),
        question_ja=question,
        hint_ja=str(data.get("hint_ja") or ""),
        reference_answer_ja=str(data.get("reference_answer_ja") or ""),
        reference_answer_en=str(data.get("reference_answer_en") or ""),
        rubric_en=[str(x) for x in _as_list(data.get("rubric_en"))],
        source_line_ids=[str(x) for x in _as_list(data.get("source_line_ids"))],
    )


# ---------------------------------------------------------------------------
# Generator
# ---------------------------------------------------------------------------


class SessionReviewGenerator:
    def __init__(self, ai_service, native_language: str = "English", logger=None, chunk_chars: int = DEFAULT_CHUNK_CHARS):
        self.ai = ai_service
        self.native_language = native_language
        self.logger = logger
        self.chunk_chars = chunk_chars

    # -- AI call wrapper -----------------------------------------------------
    def _call(self, prompt: str, kind: str, max_tokens: int) -> dict:
        raw = self.ai.generate_raw_prompt(prompt, request_kind=kind, max_tokens=max_tokens)
        try:
            return parse_json_object(raw)
        except SessionReviewError as first_error:
            if self.logger:
                self.logger.warning(f"Session review {kind}: unparseable response, retrying once ({first_error})")
            retry_prompt = prompt + "\n\nYour previous reply was not valid JSON. Reply with the JSON object only."
            raw = self.ai.generate_raw_prompt(retry_prompt, request_kind=kind, max_tokens=max_tokens)
            return parse_json_object(raw)

    def _values(self, **extra) -> dict:
        values = prompts.common_values(self.native_language)
        values.update(extra)
        return values

    # -- Stages --------------------------------------------------------------
    def digest_chunk(self, chunk: Sequence[ReviewLine], index: int, total: int, game_title: str) -> dict:
        prompt = prompts.render(
            prompts.CHUNK_DIGEST_PROMPT,
            **self._values(
                game_title=game_title,
                chunk_index=index,
                chunk_total=total,
                max_candidates=MAX_CANDIDATES_PER_CHUNK,
                dialogue=format_dialogue(chunk),
            ),
        )
        digest = self._call(prompt, "session_review_digest", DIGEST_MAX_TOKENS)
        digest.setdefault("summary_ja", "")
        digest["candidates"] = [c for c in _as_list(digest.get("candidates")) if isinstance(c, dict)]
        return digest

    def merge_digests(self, digests: Sequence[dict], game_title: str) -> dict:
        prompt = prompts.render(
            prompts.MERGE_PROMPT,
            **self._values(
                game_title=game_title,
                max_highlights=MAX_HIGHLIGHTS,
                digests=json.dumps(list(digests), ensure_ascii=False, indent=1),
            ),
        )
        merged = self._call(prompt, "session_review_merge", MERGE_MAX_TOKENS)
        if not str(merged.get("summary_ja") or "").strip():
            raise SessionReviewError("Merged review has no Japanese summary")
        return merged

    def generate_quiz(
        self,
        merged: dict,
        digests: Sequence[dict],
        lines: Sequence[ReviewLine],
        game_title: str,
        count: int,
    ) -> List[QuizQuestion]:
        """Batched so each call stays small; later batches see earlier questions to avoid repeats."""
        char_count = sum(len(ln.text) for ln in lines)
        dialogue_section = (
            prompts.render(prompts.QUIZ_DIALOGUE_SECTION, dialogue=format_dialogue(lines))
            if char_count <= QUIZ_FULL_DIALOGUE_MAX_CHARS
            else "(Full dialogue omitted for length; rely on the digests.)"
        )
        questions: List[QuizQuestion] = []
        batch_index = 0
        while len(questions) < count:
            batch_index += 1
            batch_count = min(QUIZ_BATCH_SIZE, count - len(questions))
            prompt = prompts.render(
                prompts.QUIZ_PROMPT,
                **self._values(
                    game_title=game_title,
                    count=batch_count,
                    id_prefix=f"q{batch_index}-",
                    already_asked=json.dumps([q.question_ja for q in questions], ensure_ascii=False) or "[]",
                    summary_ja=merged.get("summary_ja", ""),
                    highlights=json.dumps(merged.get("highlights", []), ensure_ascii=False, indent=1),
                    digests=json.dumps(
                        [{"summary_ja": d.get("summary_ja", ""), "events_ja": d.get("events_ja", [])} for d in digests],
                        ensure_ascii=False,
                        indent=1,
                    ),
                    dialogue_section=dialogue_section,
                ),
            )
            data = self._call(prompt, "session_review_quiz", QUIZ_MAX_TOKENS)
            batch = [
                q
                for i, raw in enumerate(_as_list(data.get("questions")))
                if isinstance(raw, dict) and (q := _question_from_dict(raw, f"q{batch_index}-{i + 1}"))
            ]
            if not batch:
                raise SessionReviewError("Quiz generation returned no questions")
            questions.extend(batch[:batch_count])
        return questions

    def grade_answer(
        self, question: QuizQuestion, answer: str, source_lines: Sequence[ReviewLine], game_title: str
    ) -> QuizGrade:
        if not answer or not answer.strip():
            raise ValueError("Enter an answer in Japanese.")
        prompt = prompts.render(
            prompts.GRADE_PROMPT,
            **self._values(
                game_title=game_title,
                question=json.dumps(asdict(question), ensure_ascii=False, indent=1),
                source_lines=format_dialogue(source_lines) or "(no source lines recorded)",
                answer=answer.strip(),
            ),
        )
        data = self._call(prompt, "session_review_grade", GRADE_MAX_TOKENS)
        verdict = str(data.get("verdict") or "").lower()
        if verdict not in {"correct", "partial", "incorrect"}:
            verdict = "partial"
        try:
            score = int(round(float(data.get("score", 0))))
        except (TypeError, ValueError):
            score = 0
        return QuizGrade(
            verdict=verdict,
            score=max(0, min(100, score)),
            feedback_ja=str(data.get("feedback_ja") or ""),
            feedback_en=str(data.get("feedback_en") or ""),
            japanese_fixes=[f for f in _as_list(data.get("japanese_fixes")) if isinstance(f, dict)],
            model_answer_ja=str(data.get("model_answer_ja") or ""),
        )

    # -- Whole pipeline ------------------------------------------------------
    def run(
        self,
        lines: Sequence[ReviewLine],
        game_title: str,
        progress: Optional[ProgressCallback] = None,
        question_count: Optional[int] = None,
    ) -> SessionReviewResult:
        lines = [ln for ln in lines if ln.text.strip()]
        if not lines:
            raise SessionReviewError("No lines in this session")
        char_count = sum(len(ln.text) for ln in lines)
        notify = progress or (lambda stage, detail: None)

        chunks = chunk_lines(lines, self.chunk_chars)
        digests: List[dict] = []
        for i, chunk in enumerate(chunks, start=1):
            notify("digest", f"{i}/{len(chunks)}")
            digests.append(self.digest_chunk(chunk, i, len(chunks), game_title))

        notify("merge", "")
        merged = self.merge_digests(digests, game_title)

        count = question_count if question_count is not None else quiz_question_count(char_count)
        notify("quiz", f"0/{count}")
        quiz = self.generate_quiz(merged, digests, lines, game_title, count) if count > 0 else []

        return SessionReviewResult(
            summary_ja=str(merged.get("summary_ja") or ""),
            summary_en=str(merged.get("summary_en") or ""),
            characters=[c for c in _as_list(merged.get("characters")) if isinstance(c, dict)],
            highlights=[_highlight_from_dict(h) for h in _as_list(merged.get("highlights")) if isinstance(h, dict)],
            may_have_missed_ja=[str(x) for x in _as_list(merged.get("may_have_missed_ja"))],
            may_have_missed_en=[str(x) for x in _as_list(merged.get("may_have_missed_en"))],
            quiz=quiz,
            digests=digests,
            line_count=len(lines),
            char_count=char_count,
        )


def build_generator(logger=None) -> SessionReviewGenerator:
    """Generator wired to the user's configured AI provider (NanoGPT via the OpenAI provider, etc.)."""
    from GameSentenceMiner.ai.service import AIService, snapshot_config
    from GameSentenceMiner.util.config.configuration import get_config
    from GameSentenceMiner.util.config.configuration import logger as default_logger

    config = get_config()
    log = logger or default_logger
    service = AIService(config_snapshot=snapshot_config(config.ai, config.general), logger=log)
    return SessionReviewGenerator(service, native_language=config.general.get_native_language_name(), logger=log)
