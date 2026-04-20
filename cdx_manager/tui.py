from __future__ import annotations

import curses
import os
from pathlib import Path

from .models import SessionInfo
from .session_store import collect_sessions, execute_delete, sorted_sessions
from .textutil import clip_text, clip_text_cells, display_title, short_session_id


def _safe_addnstr(stdscr: curses.window, y: int, x: int, text: str, max_len: int, attr: int = 0) -> None:
    if max_len <= 0:
        return
    try:
        stdscr.addnstr(y, x, text, max_len, attr)
    except curses.error:
        return


def _init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.init_pair(5, curses.COLOR_GREEN, -1)


def _detail_lines(session: SessionInfo | None) -> list[str]:
    if session is None:
        return ["No session selected."]
    return [
        "Session Detail",
        "",
        f"Title: {display_title(session)}",
        f"Short ID: {short_session_id(session.session_id)}",
        f"Full ID: {session.session_id}",
        f"Updated: {session.updated_at or '-'}",
        f"CWD: {session.cwd or '-'}",
        f"Files: {len(session.files)}",
        "",
        "First Prompt:",
        session.first_prompt or "-",
        "",
        "Session Files:",
        *([str(p) for p in session.files] if session.files else ["-"]),
    ]


def _draw_panel_border(stdscr: curses.window, top: int, left: int, height: int, width: int) -> None:
    if height < 2 or width < 2:
        return
    right = left + width - 1
    bottom = top + height - 1
    for x in range(left + 1, right):
        _safe_addnstr(stdscr, top, x, "-", 1)
        _safe_addnstr(stdscr, bottom, x, "-", 1)
    for y in range(top + 1, bottom):
        _safe_addnstr(stdscr, y, left, "|", 1)
        _safe_addnstr(stdscr, y, right, "|", 1)
    _safe_addnstr(stdscr, top, left, "+", 1)
    _safe_addnstr(stdscr, top, right, "+", 1)
    _safe_addnstr(stdscr, bottom, left, "+", 1)
    _safe_addnstr(stdscr, bottom, right, "+", 1)


def draw_tui(stdscr: curses.window, ordered: list[SessionInfo], selected: int, top: int, status: str) -> tuple[int, int]:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    header_attr = curses.color_pair(2) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
    section_attr = curses.color_pair(3) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
    selected_attr = curses.color_pair(1) | curses.A_BOLD if curses.has_colors() else curses.A_REVERSE
    status_attr = curses.color_pair(4) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
    hint_attr = curses.color_pair(5) if curses.has_colors() else curses.A_DIM

    title = "CDX Session Manager"
    subtitle = "Enter/o resume  n new  d delete  r refresh  q quit"
    _safe_addnstr(stdscr, 0, 0, " " * max(1, w - 1), w - 1, header_attr)
    _safe_addnstr(stdscr, 0, 2, title, w - 4, header_attr)
    summary = f"Total: {len(ordered)}"
    if ordered and 0 <= selected < len(ordered):
        summary += f"  Selected: {selected + 1}/{len(ordered)}"
    _safe_addnstr(stdscr, 1, 0, clip_text_cells(summary, w - 1), w - 1, hint_attr)
    _safe_addnstr(stdscr, 2, 0, clip_text_cells(subtitle, w - 1), w - 1, hint_attr)

    content_top = 3
    footer_line = h - 1
    content_height = max(1, footer_line - content_top)

    split = w >= 110
    if split:
        left_w = max(48, int(w * 0.55))
        right_w = max(30, w - left_w - 1)
    else:
        left_w = w
        right_w = 0

    left_top = content_top
    left_left = 0
    left_height = content_height
    left_width = max(1, left_w)

    if split:
        right_top = content_top
        right_left = left_w + 1
        right_height = content_height
        right_width = max(1, right_w)
        _draw_panel_border(stdscr, right_top, right_left, right_height, right_width)
        _safe_addnstr(stdscr, right_top, right_left + 2, "Details", right_width - 4, section_attr)

    list_inner_top = left_top
    list_inner_left = left_left
    list_inner_height = left_height
    list_inner_width = left_width
    if split:
        _draw_panel_border(stdscr, left_top, left_left, left_height, left_width)
        _safe_addnstr(stdscr, left_top, left_left + 2, "Sessions", left_width - 4, section_attr)
        list_inner_top += 1
        list_inner_left += 1
        list_inner_height -= 2
        list_inner_width -= 2

    per_item = 2
    visible_items = max(1, list_inner_height // per_item)
    if selected < top:
        top = selected
    if selected >= top + visible_items:
        top = selected - visible_items + 1

    for row_idx in range(visible_items):
        idx = top + row_idx
        if idx >= len(ordered):
            break
        s = ordered[idx]
        y = list_inner_top + row_idx * per_item
        marker = ">" if idx == selected else " "
        title_text = clip_text_cells(display_title(s), max(18, list_inner_width - 24))
        line1 = f"{marker} {idx + 1:>3}. {title_text}"
        line2 = f"      {short_session_id(s.session_id)}  {clip_text_cells(s.cwd or '-', max(10, list_inner_width - 20))}"
        attr = selected_attr if idx == selected else curses.A_NORMAL
        _safe_addnstr(stdscr, y, list_inner_left, line1, list_inner_width, attr)
        if y + 1 < list_inner_top + list_inner_height:
            _safe_addnstr(stdscr, y + 1, list_inner_left, line2, list_inner_width, curses.A_DIM)

    if split:
        current = ordered[selected] if ordered and 0 <= selected < len(ordered) else None
        detail_lines = _detail_lines(current)
        start_y = right_top + 1
        start_x = right_left + 1
        max_h = max(1, right_height - 2)
        max_w = max(1, right_width - 2)
        for i, line in enumerate(detail_lines[:max_h]):
            attr = section_attr if i == 0 else curses.A_NORMAL
            _safe_addnstr(stdscr, start_y + i, start_x, clip_text_cells(line, max_w), max_w, attr)

    status_text = status or "Ready."
    _safe_addnstr(stdscr, footer_line, 0, " " * max(1, w - 1), w - 1)
    _safe_addnstr(stdscr, footer_line, 0, clip_text_cells(status_text, w - 1), w - 1, status_attr)
    stdscr.refresh()
    return top, visible_items


def confirm_delete(stdscr: curses.window, text: str) -> bool:
    h, w = stdscr.getmaxyx()
    prompt = clip_text(text + " [y/N]: ", w - 1)
    stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
    stdscr.addnstr(h - 1, 0, prompt, w - 1, curses.A_BOLD)
    stdscr.refresh()
    ch = stdscr.getch()
    return ch in (ord("y"), ord("Y"))


def prompt_input(stdscr: curses.window, text: str) -> str:
    h, w = stdscr.getmaxyx()
    prompt = clip_text(text + ": ", w - 1)
    stdscr.addnstr(h - 1, 0, " " * (w - 1), w - 1)
    stdscr.addnstr(h - 1, 0, prompt, w - 1, curses.A_BOLD)
    stdscr.refresh()
    curses.echo()
    curses.curs_set(1)
    try:
        raw = stdscr.getstr(h - 1, min(len(prompt), w - 1), max(1, w - len(prompt) - 1))
        value = raw.decode("utf-8", errors="ignore").strip()
    finally:
        curses.noecho()
        curses.curs_set(0)
    return value


def run_tui(codex_home: Path) -> tuple[str, dict[str, str] | None]:
    def _inner(stdscr: curses.window) -> tuple[str, dict[str, str] | None]:
        _init_colors()
        curses.curs_set(0)
        stdscr.keypad(True)

        selected = 0
        top = 0
        status = ""

        while True:
            sessions = collect_sessions(codex_home)
            ordered = sorted_sessions(sessions)
            if selected >= len(ordered):
                selected = max(0, len(ordered) - 1)

            top, visible_items = draw_tui(stdscr, ordered, selected, top, status)
            status = ""
            ch = stdscr.getch()

            if ch in (ord("q"), ord("Q")):
                return ("quit", None)
            if ch in (curses.KEY_ENTER, 10, 13, ord("o"), ord("O")):
                if not ordered:
                    status = "No session to resume."
                    continue
                current = ordered[selected]
                payload = {"session_id": current.session_id, "cwd": current.cwd or ""}
                return ("resume", payload)
            if ch in (ord("n"), ord("N")):
                default_dir = ordered[selected].cwd if ordered else os.getcwd()
                entered = prompt_input(stdscr, f"New session dir (empty uses {default_dir})")
                target_dir = entered or default_dir or os.getcwd()
                prompt = prompt_input(stdscr, "Initial prompt (optional)")
                payload = {"cwd": target_dir, "prompt": prompt}
                return ("new", payload)
            if ch in (curses.KEY_UP, ord("k"), ord("K")):
                if selected > 0:
                    selected -= 1
                continue
            if ch in (curses.KEY_DOWN, ord("j"), ord("J")):
                if selected < len(ordered) - 1:
                    selected += 1
                continue
            if ch in (ord("g"),):
                selected = 0
                continue
            if ch in (ord("G"),):
                selected = max(0, len(ordered) - 1)
                continue
            if ch == curses.KEY_HOME:
                selected = 0
                continue
            if ch == curses.KEY_END:
                selected = max(0, len(ordered) - 1)
                continue
            if ch == curses.KEY_PPAGE:
                selected = max(0, selected - visible_items)
                continue
            if ch == curses.KEY_NPAGE:
                selected = min(max(0, len(ordered) - 1), selected + visible_items)
                continue
            if ch in (ord("r"), ord("R")):
                status = "Refreshed."
                continue
            if ch in (ord("d"), ord("D"), ord("x"), ord("X"), curses.KEY_DC):
                if not ordered:
                    status = "No session to delete."
                    continue
                current = ordered[selected]
                ok = confirm_delete(stdscr, f"Delete session {short_session_id(current.session_id)}: {clip_text(display_title(current), 50)}?")
                if not ok:
                    status = "Delete canceled."
                    continue
                removed_files, removed_index, _ = execute_delete(
                    codex_home=codex_home,
                    sessions=sessions,
                    target_ids={current.session_id},
                    dry_run=False,
                )
                status = f"Deleted {short_session_id(current.session_id)} (files={removed_files}, index={removed_index})."
                continue

            status = "Unknown key. Use Up/Down/j/k, Enter/o resume, n new, d delete, r refresh, q quit."

    return curses.wrapper(_inner)
