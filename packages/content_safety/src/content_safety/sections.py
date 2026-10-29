"""Shared Markdown heading scan for snapshot scope and observer evidence."""

import re
from dataclasses import dataclass

HEADING = re.compile(r"^(#{2,3})[ \t]+(.+?)[ \t]*#*[ \t]*$")
FENCE = re.compile(r"^[ \t]*(`{3,}|~{3,})")


@dataclass(frozen=True)
class SnapshotHeading:
    level: int
    title: str
    line_index: int


def visible_snapshot_lines(markdown: str) -> list[str]:
    """Preserve line positions while hiding fenced examples from structural checks."""
    visible: list[str] = []
    fence_char: str | None = None
    fence_width = 0
    for line in markdown.splitlines():
        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)
            if fence_char is None:
                fence_char, fence_width = marker[0], len(marker)
            elif marker[0] == fence_char and len(marker) >= fence_width:
                fence_char = None
            visible.append("")
            continue
        if fence_char is not None:
            visible.append("")
            continue
        visible.append(line)
    return visible


def snapshot_headings(markdown: str) -> list[SnapshotHeading]:
    """Find level-two and level-three headings outside fenced code blocks."""
    headings: list[SnapshotHeading] = []
    for index, line in enumerate(visible_snapshot_lines(markdown)):
        match = HEADING.fullmatch(line)
        if match:
            marker, title = match.groups()
            headings.append(SnapshotHeading(len(marker), title.strip(), index))
    return headings
