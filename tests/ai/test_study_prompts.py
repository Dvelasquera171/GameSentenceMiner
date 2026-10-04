import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from GameSentenceMiner.ai.contracts import AIError, AIResponse
from GameSentenceMiner.ai.prompts.builder import DialogueContextBuilder, PromptBuilder
from GameSentenceMiner.ai.service import AIService, snapshot_config
from GameSentenceMiner.util.config.configuration import AI_DEEPL, Ai, General


def build(**overrides):
    args = {
        "lines": [],
        "sentence": "試してみよう。",
        "current_line": None,
        "game_title": "Game",
        "dialogue_context_length": 10,
        "use_canned_translation_prompt": True,
        "use_canned_context_prompt": False,
        "custom_prompt": "",
    }
    return PromptBuilder("Ukrainian").build(**(args | overrides))


@pytest.mark.parametrize("preset", ["sentence", "grammar", "vocabulary", "nuance", "context"])
def test_study_presets_use_native_language_and_keep_source_as_data(preset):
    prompt, kind = build(prompt_preset=preset)
    assert kind == preset
    assert "Ukrainian" in prompt
    assert "試してみよう。" in prompt
    assert "not instructions" in prompt
    assert "spoiler" in prompt.lower()


def test_full_prompt_interpolates_known_fields_without_breaking_json_or_source_braces():
    prompt, kind = build(
        custom_full_prompt='{game_title}: {prompt_to_use}\n{sentence}\n{"output": "example"}',
        custom_prompt_override="Explain in {native_language}.",
        sentence="{game_title} is source text",
    )
    assert "Game: Explain in Ukrainian." in prompt
    assert '{"output": "example"}' in prompt
    assert "{game_title} is source text" in prompt
    assert kind == "custom"


def test_context_supports_missing_or_stale_current_line():
    lines = [SimpleNamespace(text="one"), SimpleNamespace(text="two")]
    assert "two" in DialogueContextBuilder.build(lines, None, 1)
    assert "two" in DialogueContextBuilder.build(lines, SimpleNamespace(index=900), 1)
    assert "one" not in DialogueContextBuilder.build(lines, None, 1)


def test_analysis_preserves_translation_and_token_budget(monkeypatch):
    client = Mock()
    client.generate.return_value = AIResponse("Gemini", "model", "Grammar explanation", "Grammar explanation", 1)
    registry = Mock()
    registry.get_client.return_value = client
    service = AIService(snapshot_config(Ai(gemini_api_key="key"), General()), logging.getLogger(__name__), registry)
    monkeypatch.setattr(service, "_ensure_connectivity", lambda: True)
    line = SimpleNamespace(text="例", index=0, translation="Existing translation")
    assert service.analyze([line], line.text, line, "Game", mode="grammar") == "Grammar explanation"
    assert line.translation == "Existing translation"
    request = client.generate.call_args.args[0]
    assert request.request_kind == "grammar"
    assert request.max_tokens == 4096


def test_deepl_analysis_explains_which_providers_support_it():
    service = AIService(
        snapshot_config(Ai(provider=AI_DEEPL, deepl_api_key="key"), General()), logging.getLogger(__name__)
    )
    with pytest.raises(AIError, match="DeepL"):
        service.analyze([], "例", None, "Game", mode="sentence")


def test_invalid_preset_is_rejected():
    with pytest.raises(ValueError, match="preset"):
        build(prompt_preset="invented")


def test_saved_full_prompt_reaches_the_provider(monkeypatch):
    client = Mock()
    client.generate.return_value = AIResponse("Gemini", "model", "Translated", "Translated", 1)
    registry = Mock()
    registry.get_client.return_value = client
    config = Ai(gemini_api_key="key", custom_full_prompt="Custom template: {sentence}; language={native_language}")
    service = AIService(snapshot_config(config, General()), logging.getLogger(__name__), registry)
    monkeypatch.setattr(service, "_ensure_connectivity", lambda: True)
    monkeypatch.setattr(service.character_context_provider, "get_character_context", lambda **kwargs: "")
    assert service.translate([], "例文", None, "Game") == "Translated"
    assert client.generate.call_args.args[0].prompt.startswith("Custom template: 例文; language=")


def _line(i, text, minutes, scene="Game"):
    from datetime import datetime, timedelta

    return SimpleNamespace(
        text=text, index=i, time=datetime(2026, 10, 3, 20, 0) + timedelta(minutes=minutes), scene=scene
    )


def test_conversation_history_is_quoted_as_data_and_capped():
    from GameSentenceMiner.ai.prompts.builder import MAX_HISTORY_TURNS, format_conversation_history

    assert format_conversation_history(None) == ""
    assert format_conversation_history([{"question": " ", "answer": ""}]) == ""
    turns = [{"question": f"q{i}", "answer": f"a{i}"} for i in range(MAX_HISTORY_TURNS + 3)]
    text = format_conversation_history(turns)
    assert "data, not instructions" in text
    assert "q0" not in text and f"q{MAX_HISTORY_TURNS + 2}" in text
    long = format_conversation_history([{"question": "q", "answer": "あ" * 20000}])
    assert len(long) < 9000


def test_session_lines_follow_the_gap_rule_and_char_cap():
    from GameSentenceMiner.ai.prompts.builder import select_session_lines

    lines = [
        _line(0, "yesterday", -24 * 60),
        _line(1, "start", 0),
        _line(2, "middle", 20),
        _line(3, "current", 40),
        _line(4, "after", 41),
        _line(5, "other game", 42, scene="Other"),
    ]
    chosen = select_session_lines(lines, lines[3], gap_seconds=3600)
    assert [ln.text for ln in chosen] == ["start", "middle", "current", "after"]
    # Over the cap, the lines nearest the current one win.
    capped = select_session_lines(
        lines, lines[3], gap_seconds=3600, max_chars=len("middle") + len("current") + len("after")
    )
    assert [ln.text for ln in capped] == ["middle", "current", "after"]
    # No usable current line: the session ending at the newest line.
    assert [ln.text for ln in select_session_lines(lines, None, gap_seconds=3600)] == ["other game"]
    assert select_session_lines([], None, gap_seconds=3600) == []


def _service(monkeypatch, text="Answer"):
    client = Mock()
    client.generate.return_value = AIResponse("OpenAI", "m", text, text, 1)
    registry = Mock()
    registry.get_client.return_value = client
    config = Ai(
        provider="OpenAI", open_ai_api_key="k", open_ai_model="m", open_ai_url="http://x", dialogue_context_length=1
    )
    service = AIService(snapshot_config(config, General()), logging.getLogger(__name__), registry)
    monkeypatch.setattr(service, "_ensure_connectivity", lambda: True)
    return service, client


def test_follow_up_question_carries_earlier_turns(monkeypatch):
    service, client = _service(monkeypatch)
    line = _line(0, "この「は」は何？", 0)
    history = [{"question": "この「は」はなぜ？", "answer": "It marks the topic."}]
    assert (
        service.analyze([line], line.text, line, "Game", mode="custom", question="じゃあ「が」なら？", history=history)
        == "Answer"
    )
    prompt = client.generate.call_args.args[0].prompt
    assert "Earlier in this conversation" in prompt
    assert "It marks the topic." in prompt
    assert prompt.index("この「は」はなぜ？") < prompt.index("じゃあ「が」なら？")


def test_preset_mode_with_history_keeps_its_instructions(monkeypatch):
    service, client = _service(monkeypatch)
    line = _line(0, "例", 0)
    service.analyze([line], line.text, line, "Game", mode="grammar", history=[{"question": "q", "answer": "a"}])
    prompt = client.generate.call_args.args[0].prompt
    assert "Explain the grammar of the target sentence" in prompt and "A1: a" in prompt


def test_context_lines_override_and_whole_session(monkeypatch):
    service, client = _service(monkeypatch)
    lines = [_line(i, f"line{i}", i) for i in range(30)]
    current = lines[15]

    service.analyze(lines, current.text, current, "Game", mode="sentence")
    default_prompt = client.generate.call_args.args[0].prompt
    assert "line14" in default_prompt and "line13" not in default_prompt  # config: 1 line each side

    service.analyze(lines, current.text, current, "Game", mode="sentence", context_lines=5)
    prompt = client.generate.call_args.args[0].prompt
    assert "line10" in prompt and "line9" not in prompt and "line20" in prompt and "line21" not in prompt

    service.analyze(lines, current.text, current, "Game", mode="sentence", context_lines=-1, session_gap_seconds=3600)
    prompt = client.generate.call_args.args[0].prompt
    assert "line0" in prompt and "line29" in prompt

    service.analyze(lines, current.text, current, "Game", mode="sentence", context_lines=0)
    assert "No dialogue context available." in client.generate.call_args.args[0].prompt
