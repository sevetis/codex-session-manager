from __future__ import annotations

import curses

from .textutil import clip_text, clip_text_cells


def confirm_delete(stdscr: curses.window, text: str) -> bool:
    h, w = stdscr.getmaxyx()
    prompt = clip_text(text + " [y/N]: ", w - 1)
    stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
    stdscr.addnstr(h - 1, 0, prompt, w - 1, curses.A_BOLD)
    stdscr.refresh()
    ch = stdscr.getch()
    return ch in (ord("y"), ord("Y"))


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
