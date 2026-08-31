from piper.windows_tray.codex_text import (
    MAX_CODEX_SPEECH_CHARS,
    prepare_codex_speech,
)


def test_codex_text_normalizes_blank_lines_and_line_edges() -> None:
    assert prepare_codex_speech("  First  \r\n\r\n\r\n Second \n") == "First\n\nSecond"


def test_codex_text_removes_only_closed_fenced_code_blocks() -> None:
    text = "Before\n```python\nprint('secret')\n```\nAfter"
    assert prepare_codex_speech(text) == "Before\n\nAfter"


def test_unmatched_code_fence_is_preserved_instead_of_guessed() -> None:
    text = "Before\n```python\nprint('still visible')\nAfter"
    assert prepare_codex_speech(text) == text


def test_empty_or_code_only_response_is_skipped() -> None:
    assert prepare_codex_speech("   \n") is None
    assert prepare_codex_speech("```\nprint('x')\n```\n") is None


def test_codex_text_is_capped_at_exact_policy_limit() -> None:
    text = ("word " * 2_000).strip()
    prepared = prepare_codex_speech(text)
    assert prepared is not None
    assert len(prepared) <= MAX_CODEX_SPEECH_CHARS
    assert MAX_CODEX_SPEECH_CHARS == 6_000
    assert not prepared.endswith(" ")


def test_tilde_fences_are_removed_when_closed() -> None:
    assert prepare_codex_speech("A\n~~~\ncode\n~~~\nB") == "A\n\nB"


def test_no_whitespace_near_limit_cuts_exactly_at_limit() -> None:
    prepared = prepare_codex_speech("x" * 6_001)
    assert prepared == "x" * MAX_CODEX_SPEECH_CHARS


def test_markdown_links_speak_visible_labels_only() -> None:
    text = "See [the setup guide](https://example.com/guide) and [settings](C:\\Projects\\Piper\\settings.json)."
    assert prepare_codex_speech(text) == "See the setup guide and settings."


def test_markdown_link_preserves_surrounding_punctuation() -> None:
    text = "Open [Piper](https://example.com/piper), then continue."
    assert prepare_codex_speech(text) == "Open Piper, then continue."


def test_empty_markdown_link_label_drops_destination_but_keeps_context() -> None:
    text = "Before [](/tmp/hidden.txt) after."
    assert prepare_codex_speech(text) == "Before  after."


def test_raw_urls_and_paths_remain_unchanged() -> None:
    text = "Visit https://example.com/a/very/long/path?tracking=true or C:\\Projects\\Piper."
    assert prepare_codex_speech(text) == "Visit example.com or C:\\Projects\\Piper."


def test_bare_urls_keep_the_host_and_drop_paths() -> None:
    text = "Use www.google.com/search?q=piper or https://docs.python.org/3/library/"
    assert prepare_codex_speech(text) == "Use www.google.com or docs.python.org"


def test_images_and_malformed_links_are_preserved() -> None:
    image = "![diagram](https://example.com/diagram.png)"
    malformed = "Keep [this text](https://example.com"
    assert prepare_codex_speech(image) == image
    assert prepare_codex_speech(malformed) == malformed
