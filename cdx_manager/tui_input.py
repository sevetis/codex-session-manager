from __future__ import annotations

import curses

from .textutil import clip_text, clip_text_cells


def confirm_delete(stdscr: curses.window, text: str) -> bool:
    h, w = stdscr.getmaxyx()
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if not lines:
        lines = ["Delete selected session?"]
    lines.append("")
    lines.append("This cannot be undone.")
    lines.append("Press y to confirm, n/Esc to cancel.")

    inner_w = min(max(40, max(len(ln) for ln in lines) + 2), max(24, w - 4))
    inner_h = min(max(8, len(lines) + 2), max(6, h - 4))
    box_w = inner_w + 2
    box_h = inner_h + 2
    x0 = max(0, (w - box_w) // 2)
    y0 = max(0, (h - box_h) // 2)

    # Border
    try:
        stdscr.addnstr(y0, x0, "+" + ("-" * inner_w) + "+", box_w, curses.A_BOLD)
        for i in range(1, box_h - 1):
            stdscr.addnstr(y0 + i, x0, "|", 1, curses.A_BOLD)
            stdscr.addnstr(y0 + i, x0 + box_w - 1, "|", 1, curses.A_BOLD)
            stdscr.addnstr(y0 + i, x0 + 1, " " * inner_w, inner_w)
        stdscr.addnstr(y0 + box_h - 1, x0, "+" + ("-" * inner_w) + "+", box_w, curses.A_BOLD)
    except curses.error:
        pass

    # Content
    for i, raw in enumerate(lines[:inner_h]):
        try:
            attr = curses.A_BOLD if i == 0 else curses.A_NORMAL
            stdscr.addnstr(y0 + 1 + i, x0 + 1, clip_text_cells(raw, inner_w), inner_w, attr)
        except curses.error:
            pass

    stdscr.refresh()
    while True:
        ch = stdscr.getch()
        if ch in (ord("y"), ord("Y")):
            return True
        if ch in (ord("n"), ord("N"), 27):
            return False


def prompt_input(stdscr: curses.window, text: str) -> str | None:
    h, w = stdscr.getmaxyx()
    prompt = clip_text(text + " (Esc cancel): ", w - 1)
    chars: list[str] = []
    curses.curs_set(1)
    try:
        while True:
            stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
            stdscr.addnstr(h - 1, 0, prompt, w - 1, curses.A_BOLD)
            max_input = max(1, w - len(prompt) - 1)
            current = "".join(chars)
            stdscr.addnstr(h - 1, min(len(prompt), w - 1), clip_text_cells(current, max_input), max_input)
            stdscr.refresh()

            ch = stdscr.get_wch()
            if ch in ("\n", "\r"):
                return "".join(chars).strip()
            if ch == "\x1b":
                return None
            if ch in (curses.KEY_BACKSPACE, "\b", "\x7f", curses.KEY_DC):
                if chars:
                    chars.pop()
                continue
            if isinstance(ch, str) and ch.isprintable():
                chars.append(ch)
    finally:
        curses.curs_set(0)
