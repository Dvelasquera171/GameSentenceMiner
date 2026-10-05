from types import SimpleNamespace

import pytest

from GameSentenceMiner import gametext


def test_v2_ingress_files_a_browser_line_under_its_own_title(monkeypatch):
    captured = {}

    def fake_ingest(text, **kwargs):
        captured.update(kwargs, text=text)
        return SimpleNamespace(to_dict=lambda: {"status": "accepted"})

    monkeypatch.setattr(gametext, "_ingest_line_sync", fake_ingest)

    result = gametext.ingest_text_v2_payload(
        {
            "text": "やっと会えたね",
            "source": "browser",
            "title": "  葬送のフリーレン  ",
            "url": "https://www.youtube.com/watch?v=abc",
            "skip_overlay": True,
        }
    )

    assert result == {"status": "accepted"}
    assert captured["text"] == "やっと会えたね"
    assert captured["metadata_extra"] == {"scene": "葬送のフリーレン", "url": "https://www.youtube.com/watch?v=abc"}
    assert captured["skip_overlay"] is True


def test_v2_ingress_without_title_keeps_the_current_game(monkeypatch):
    captured = {}
    monkeypatch.setattr(
        gametext,
        "_ingest_line_sync",
        lambda text, **kwargs: captured.update(kwargs) or SimpleNamespace(to_dict=lambda: {"status": "accepted"}),
    )

    gametext.ingest_text_v2_payload({"text": "hook line", "source": "texthook", "hookId": "7"})

    assert captured["metadata_extra"] == {"hookId": "7"}
    assert captured["skip_overlay"] is False


def test_browser_lines_skip_the_skip_spam_filter(monkeypatch):
    class PastRateLimit(Exception):
        pass

    monkeypatch.setattr(
        gametext,
        "is_message_rate_limited",
        lambda source: (_ for _ in ()).throw(AssertionError(f"rate limit checked for {source}")),
    )
    monkeypatch.setattr(
        gametext,
        "apply_text_processing",
        lambda *_a, **_k: (_ for _ in ()).throw(PastRateLimit()),
    )
    monkeypatch.setattr(
        gametext,
        "get_config",
        lambda: SimpleNamespace(general=SimpleNamespace(texthook_max_buffer_size=3000), text_processing=None),
    )

    with pytest.raises(PastRateLimit):
        gametext._ingest_line_sync("manga bubble", source="browser", source_display_name="GSM Connect · Manatan")


def test_anki_recognizes_the_browser_source_by_name():
    import ast
    from pathlib import Path

    from GameSentenceMiner.text_pipeline.models import SourceKind

    tree = ast.parse(Path(gametext.__file__).with_name("anki.py").read_text(encoding="utf-8"))
    values = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "BROWSER_LINE_SOURCE" for t in node.targets)
    ]
    assert values == [SourceKind.BROWSER.value]
