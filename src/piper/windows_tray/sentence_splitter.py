"""Conservative sentence splitting for queued tray speech."""

from __future__ import annotations

import re

_COMMON_ABBREVIATIONS = frozenset(
    {
        "dr.",
        "e.g.",
        "i.e.",
        "jr.",
        "mr.",
        "mrs.",
        "ms.",
        "no.",
        "prof.",
        "sr.",
        "st.",
        "vs.",
    }
)
_DOTTED_INITIALISM = re.compile(r"(?:[A-Za-z]\.){2,}$")
_SENTENCE_TERMINATORS = ".!?…"
_TRAILING_CLOSERS = "\"'”’)]}"


def _period_is_protected(text: str, index: int) -> bool:
    before = text[index - 1] if index > 0 else ""
    after = text[index + 1] if index + 1 < len(text) else ""
    if before.isdigit() and after.isdigit():
        return True

    start = index
    while start > 0:
        previous = text[start - 1]
        if not (previous.isalpha() or previous == "."):
            break
        start -= 1

    token = text[start : index + 1]
    token_lower = token.lower()
    return (
        token_lower in _COMMON_ABBREVIATIONS
        or _DOTTED_INITIALISM.fullmatch(token) is not None
    )


def split_speech_sentences(text: str) -> tuple[str, ...]:
    """Split text at conservative sentence boundaries, keeping punctuation."""
    if not text.strip():
        return ()

    sentences: list[str] = []
    start = 0
    index = 0
    text_length = len(text)

    while index < text_length:
        if text[index] not in _SENTENCE_TERMINATORS:
            index += 1
            continue

        punctuation_end = index + 1
        while (
            punctuation_end < text_length
            and text[punctuation_end] in _SENTENCE_TERMINATORS
        ):
            punctuation_end += 1

        if (
            text[index] == "."
            and punctuation_end == index + 1
            and _period_is_protected(text, index)
        ):
            index += 1
            continue

        sentence_end = punctuation_end
        while (
            sentence_end < text_length
            and text[sentence_end] in _TRAILING_CLOSERS
        ):
            sentence_end += 1

        if sentence_end < text_length and not text[sentence_end].isspace():
            index = punctuation_end
            continue

        sentence = text[start:sentence_end].strip()
        if sentence:
            sentences.append(sentence)

        while sentence_end < text_length and text[sentence_end].isspace():
            sentence_end += 1
        start = sentence_end
        index = sentence_end

    tail = text[start:].strip()
    if tail:
        sentences.append(tail)

    return tuple(sentences)
