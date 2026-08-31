"""Prepare Codex answers for predictable speech."""

import re
from typing import List, Optional, Tuple
from urllib.parse import urlsplit


MAX_CODEX_SPEECH_CHARS = 6_000
_MIN_PREFERRED_CUT = 4_800


def _fence(line: str) -> Optional[Tuple[str, int]]:
    stripped = line.lstrip()
    if not stripped or stripped[0] not in {"`", "~"}:
        return None
    marker = stripped[0]
    count = 0
    for char in stripped:
        if char != marker:
            break
        count += 1
    return (marker, count) if count >= 3 else None


def _without_closed_fenced_blocks(text: str) -> str:
    lines = text.split("\n")
    ranges: List[Tuple[int, int]] = []
    opening: Optional[Tuple[int, str, int]] = None
    for index, line in enumerate(lines):
        current = _fence(line)
        if current is None:
            continue
        marker, count = current
        if opening is None:
            opening = (index, marker, count)
            continue
        start, open_marker, open_count = opening
        if marker == open_marker and count >= open_count:
            ranges.append((start, index))
            opening = None
    removed = set()
    starts = {}
    for start, end in ranges:
        removed.update(range(start, end + 1))
        starts[start] = end
    output = []
    index = 0
    while index < len(lines):
        if index in starts:
            output.append("")
            index = starts[index] + 1
        elif index in removed:
            index += 1
        else:
            output.append(lines[index])
            index += 1
    return "\n".join(output)


def _replace_markdown_links(text: str) -> str:
    """Replace balanced inline Markdown links with their visible labels."""
    output = []
    index = 0
    while index < len(text):
        if text[index] != "[" or (index > 0 and text[index - 1] == "!"):
            output.append(text[index])
            index += 1
            continue

        label_end = text.find("]", index + 1)
        if label_end == -1 or label_end + 1 >= len(text) or text[label_end + 1] != "(":
            output.append(text[index])
            index += 1
            continue

        destination_end = label_end + 2
        depth = 1
        while destination_end < len(text) and depth:
            if text[destination_end] == "(":
                depth += 1
            elif text[destination_end] == ")":
                depth -= 1
            destination_end += 1

        if depth:
            output.append(text[index])
            index += 1
            continue

        output.append(text[index + 1 : label_end])
        index = destination_end

    return "".join(output)


_BARE_URL_RE = re.compile(r"(?<![\w@])(?:https?://|www\.)[^\s<>\]]+")


def _is_markdown_destination(text: str, start: int) -> bool:
    """Keep Markdown destinations unchanged while scanning bare URLs."""
    opener = text.rfind("](", 0, start)
    return (
        opener != -1
        and text.rfind(")", opener + 2, start) == -1
    )


def _replace_bare_urls(text: str) -> str:
    """Replace bare URLs with their host names."""
    output = []
    previous_end = 0
    for match in _BARE_URL_RE.finditer(text):
        output.append(text[previous_end : match.start()])
        token = match.group(0).rstrip(".,!?;:")
        while token.endswith(")") and token.count(")") > token.count("("):
            token = token[:-1]
        if _is_markdown_destination(text, match.start()):
            output.append(match.group(0))
        else:
            parsed = urlsplit(token if "://" in token else "https://" + token)
            host = parsed.hostname
            if host is None:
                output.append(match.group(0))
            elif token.lower().startswith("www.") and not host.lower().startswith(
                "www."
            ):
                output.append("www." + host)
            else:
                output.append(host)
            output.append(match.group(0)[len(token) :])
        previous_end = match.end()
    output.append(text[previous_end:])
    return "".join(output)


def prepare_codex_speech(text: str) -> Optional[str]:
    normalized_newlines = text.replace("\r\n", "\n").replace("\r", "\n")
    without_code = _without_closed_fenced_blocks(normalized_newlines)
    without_links = _replace_markdown_links(without_code)
    without_urls = _replace_bare_urls(without_links)
    output = []
    previous_blank = False
    for raw_line in without_urls.split("\n"):
        line = raw_line.strip()
        blank = not line
        if blank and previous_blank:
            continue
        output.append(line)
        previous_blank = blank
    prepared = "\n".join(output).strip()
    if not prepared:
        return None
    if len(prepared) <= MAX_CODEX_SPEECH_CHARS:
        return prepared
    candidate = prepared[:MAX_CODEX_SPEECH_CHARS]
    boundary = max(candidate.rfind("\n"), candidate.rfind(" "))
    if boundary >= _MIN_PREFERRED_CUT:
        candidate = candidate[:boundary]
    return candidate.rstrip() or None
