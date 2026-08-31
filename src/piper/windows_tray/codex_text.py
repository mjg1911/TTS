"""Prepare Codex answers for predictable speech."""

from typing import List, Optional, Tuple


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


def prepare_codex_speech(text: str) -> Optional[str]:
    normalized_newlines = text.replace("\r\n", "\n").replace("\r", "\n")
    without_code = _without_closed_fenced_blocks(normalized_newlines)
    output = []
    previous_blank = False
    for raw_line in without_code.split("\n"):
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
