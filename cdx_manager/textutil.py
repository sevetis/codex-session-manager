from __future__ import annotations

import unicodedata

from .models import SessionInfo


def short_session_id(sid: str) -> str:
    return f"{sid[:8]}...{sid[-4:]}"


def clip_text(text: str, limit: int = 70) -> str:
    one_line = " ".join(text.split())
    if len(one_line) <= limit:
        return one_line
    return one_line[: limit - 3] + "..."


def char_cell_width(ch: str) -> int:
    if not ch:
        return 0
    if unicodedata.combining(ch):
        return 0
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    return 1


def text_cell_width(text: str) -> int:
    return sum(char_cell_width(ch) for ch in text)


def clip_text_cells(text: str, max_cells: int) -> str:
    if max_cells <= 0:
        return ""
    one_line = " ".join(text.split())
    if text_cell_width(one_line) <= max_cells:
        return one_line

    suffix = "..."
    suffix_w = text_cell_width(suffix)
    if suffix_w >= max_cells:
        return "." * max(1, min(3, max_cells))

    out: list[str] = []
    used = 0
    budget = max_cells - suffix_w
    for ch in one_line:
        w = char_cell_width(ch)
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return "".join(out) + suffix


def pad_text_cells(text: str, target_cells: int) -> str:
    if target_cells <= 0:
        return ""
    clipped = clip_text_cells(text, target_cells)
    used = text_cell_width(clipped)
    if used >= target_cells:
        return clipped
    return clipped + (" " * (target_cells - used))


def display_title(s: SessionInfo) -> str:
    if s.thread_name and s.thread_name.strip():
        return s.thread_name.strip()
    if s.first_prompt and s.first_prompt.strip():
        return clip_text(s.first_prompt.strip(), limit=70)
    return "(untitled)"
