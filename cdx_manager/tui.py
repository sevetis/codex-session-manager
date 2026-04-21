from __future__ import annotations

import curses
import os
from pathlib import Path
from typing import Any

from .codex_ops import switch_tmux_window
from .models import SessionInfo
from .session_store import collect_sessions, execute_delete, sorted_sessions
from .textutil import char_cell_width, clip_text, clip_text_cells, display_title, pad_text_cells, short_session_id, text_cell_width

VIEW_TIME = "time"
VIEW_CWD = "cwd"
VIEW_MODES = (VIEW_TIME, VIEW_CWD)


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
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)   # selected row
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)  # top header
    curses.init_pair(3, curses.COLOR_CYAN, -1)                    # panel titles
    curses.init_pair(4, curses.COLOR_YELLOW, -1)                  # status line
    curses.init_pair(5, curses.COLOR_GREEN, -1)                   # hints/summary
    curses.init_pair(6, curses.COLOR_BLUE, -1)                    # detail keys (same tone as cwd group headers)
    curses.init_pair(7, curses.COLOR_WHITE, -1)                   # detail values
    curses.init_pair(8, curses.COLOR_BLUE, -1)                    # group headers


def _detail_lines(session: SessionInfo | None) -> list[tuple[str, str] | str]:
    if session is None:
        return ["No session selected."]
    return [
        ("title", display_title(session)),
        ("short_id", short_session_id(session.session_id)),
        ("full_id", session.session_id),
        ("updated_at", session.updated_at or "-"),
        ("cwd", session.cwd or "-"),
        ("files_count", str(len(session.files))),
        "",
        ("first_prompt", session.first_prompt or "-"),
        "",
        "session_files",
        *([("session_file", str(p)) for p in session.files] if session.files else [("session_file", "-")]),
    ]


def _wrap_text_cells(text: str, max_cells: int, max_lines: int) -> list[str]:
    if max_lines <= 0:
        return []
    if max_cells <= 0:
        return [""]
    src = text if isinstance(text, str) else str(text)
    if not src:
        return [""]

    lines: list[str] = []
    current: list[str] = []
    used = 0
    for ch in src:
        if ch == "\n":
            lines.append("".join(current))
            current = []
            used = 0
            if len(lines) >= max_lines:
                break
            continue
        w = char_cell_width(ch)
        if used + w > max_cells:
            lines.append("".join(current))
            current = [ch]
            used = w
            if len(lines) >= max_lines:
                break
            continue
        current.append(ch)
        used += w

    if len(lines) < max_lines and current:
        lines.append("".join(current))

    # If truncated, suffix ellipsis on the last visible line.
    original_width = text_cell_width(src)
    visible_width = sum(text_cell_width(x) for x in lines)
    if visible_width < original_width and lines:
        lines[-1] = clip_text_cells(lines[-1], max_cells)
    return lines[:max_lines] if lines else [""]


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


def _normalized_cwd(s: SessionInfo) -> str:
    cwd = (s.cwd or "").strip()
    return cwd if cwd else "(no cwd)"


def _entry_header(title: str) -> dict[str, Any]:
    return {"type": "header", "title": title}


def _entry_session(s: SessionInfo) -> dict[str, Any]:
    return {"type": "session", "session": s}


def build_entries(ordered: list[SessionInfo], view_mode: str) -> list[dict[str, Any]]:
    if view_mode == VIEW_TIME:
        return [_entry_session(s) for s in ordered]

    groups: dict[str, list[SessionInfo]] = {}
    for s in ordered:
        key = _normalized_cwd(s)
        groups.setdefault(key, []).append(s)

    group_items = []
    for cwd, items in groups.items():
        items_sorted = sorted(items, key=lambda x: (x.updated_at or "", x.session_id), reverse=True)
        latest = items_sorted[0].updated_at or ""
        group_items.append((cwd, items_sorted, latest))
    group_items.sort(key=lambda t: (t[2], t[0]), reverse=True)

    entries: list[dict[str, Any]] = []
    for cwd, items, _latest in group_items:
        entries.append(_entry_header(f"{cwd} ({len(items)})"))
        for s in items:
            entries.append(_entry_session(s))
    return entries


def selectable_rows(entries: list[dict[str, Any]]) -> list[int]:
    return [i for i, e in enumerate(entries) if e.get("type") == "session"]


def session_from_entry(entry: dict[str, Any]) -> SessionInfo | None:
    if entry.get("type") != "session":
        return None
    s = entry.get("session")
    return s if isinstance(s, SessionInfo) else None


def format_view_mode(view_mode: str) -> str:
    if view_mode == VIEW_CWD:
        return "group-by-cwd"
    return "time"


def draw_tui(
    stdscr: curses.window,
    entries: list[dict[str, Any]],
    selected_row: int,
    top: int,
    status: str,
    view_mode: str,
) -> tuple[int, int]:
    stdscr.erase()
    h, w = stdscr.getmaxyx()
    header_attr = curses.color_pair(2) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
    section_attr = curses.color_pair(3) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
    selected_attr = curses.color_pair(1) | curses.A_BOLD if curses.has_colors() else (curses.A_REVERSE | curses.A_BOLD)
    status_attr = curses.color_pair(4) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
    hint_attr = curses.color_pair(5) if curses.has_colors() else curses.A_DIM
    detail_key_attr = curses.color_pair(6) | curses.A_BOLD if curses.has_colors() else curses.A_BOLD
    detail_val_attr = curses.color_pair(7) if curses.has_colors() else curses.A_NORMAL
    group_header_attr = curses.color_pair(8) | curses.A_BOLD if curses.has_colors() else section_attr

    title = "CDX Session Manager"
    _safe_addnstr(stdscr, 0, 0, " " * max(1, w - 1), w - 1, header_attr)
    _safe_addnstr(stdscr, 0, 2, title, w - 4, header_attr)
    selectable = selectable_rows(entries)
    selected_pos = selectable.index(selected_row) + 1 if selected_row in selectable else 0
    summary = f"Total: {len(selectable)}  View: {format_view_mode(view_mode)}"
    if selectable:
        summary += f"  Selected: {selected_pos}/{len(selectable)}"
    _safe_addnstr(stdscr, 1, 2, clip_text_cells(summary, w - 4), w - 4, hint_attr)

    content_top = 2
    footer_help_line = h - 1
    footer_status_line = h - 2 if h >= 6 else h - 1
    content_height = max(1, footer_status_line - content_top)

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

    per_item = 1
    visible_items = max(1, list_inner_height // per_item)
    if selected_row < top:
        top = selected_row
    if selected_row >= top + visible_items:
        top = selected_row - visible_items + 1

    for row_idx in range(visible_items):
        idx = top + row_idx
        if idx >= len(entries):
            break
        e = entries[idx]
        y = list_inner_top + row_idx * per_item
        if e.get("type") == "header":
            header = f"[{clip_text_cells(str(e.get('title', '')), max(6, list_inner_width - 2))}]"
            _safe_addnstr(stdscr, y, list_inner_left, header, list_inner_width, group_header_attr)
            continue

        s = session_from_entry(e)
        if s is None:
            continue
        marker = ">" if idx == selected_row else " "
        id_text = short_session_id(s.session_id)
        fixed_prefix = f"{marker} "
        id_col = 14
        title_max = max(12, min(38, list_inner_width // 2))
        title_col = pad_text_cells(display_title(s), title_max)
        id_col_text = pad_text_cells(id_text, id_col)
        used_cells = text_cell_width(fixed_prefix) + title_max + 2 + id_col + 2
        cwd_max = max(6, list_inner_width - used_cells)
        cwd_text = clip_text_cells(s.cwd or "-", cwd_max)
        line = f"{fixed_prefix}{title_col}  {id_col_text}  {cwd_text}"
        attr = selected_attr if idx == selected_row else curses.A_NORMAL
        _safe_addnstr(stdscr, y, list_inner_left, line, list_inner_width, attr)

    if split:
        current = session_from_entry(entries[selected_row]) if entries and 0 <= selected_row < len(entries) else None
        detail_rows = _detail_lines(current)
        start_y = right_top + 1
        start_x = right_left + 1
        max_h = max(1, right_height - 2)
        max_w = max(1, right_width - 2)
        y_off = 0
        for idx_row, row in enumerate(detail_rows):
            if y_off >= max_h:
                break
            y = start_y + y_off

            if isinstance(row, str):
                if row:
                    _safe_addnstr(stdscr, y, start_x, clip_text_cells(row, max_w), max_w, detail_key_attr)
                y_off += 1
                continue

            key, value = row
            if key == "first_prompt":
                _safe_addnstr(stdscr, y, start_x, "first_prompt", max_w, detail_key_attr)
                y_off += 1
                if y_off >= max_h:
                    break
                val_x = start_x + 2
                val_w = max(1, max_w - 2)
                wrapped = _wrap_text_cells(value.strip(), val_w, max_h - y_off)
                for cont in wrapped:
                    if y_off >= max_h:
                        break
                    _safe_addnstr(stdscr, start_y + y_off, val_x, cont, val_w, detail_val_attr)
                    y_off += 1
                continue

            if key == "session_file":
                val_x = start_x + 2
                val_w = max(1, max_w - 2)
                wrapped = _wrap_text_cells(value.strip(), val_w, max_h - y_off)
                for cont in wrapped:
                    if y_off >= max_h:
                        break
                    _safe_addnstr(stdscr, start_y + y_off, val_x, cont, val_w, detail_val_attr)
                    y_off += 1
                continue

            key_text = f"{key:<12}" if key else " " * 12
            key_cells = min(max_w, len(key_text) + 1)
            val_w = max(1, max_w - key_cells)
            wrapped = _wrap_text_cells(value.strip(), val_w, max_h - y_off)
            if not wrapped:
                wrapped = [""]

            _safe_addnstr(stdscr, y, start_x, key_text, key_cells, detail_key_attr)
            _safe_addnstr(stdscr, y, start_x + key_cells, wrapped[0], val_w, detail_val_attr)
            y_off += 1

            for cont in wrapped[1:]:
                if y_off >= max_h:
                    break
                y = start_y + y_off
                _safe_addnstr(stdscr, y, start_x, " " * key_cells, key_cells, detail_key_attr)
                _safe_addnstr(stdscr, y, start_x + key_cells, cont, val_w, detail_val_attr)
                y_off += 1

    status_text = f"Status: {status}" if status else "Status: idle"
    _safe_addnstr(stdscr, footer_status_line, 0, " " * max(1, w - 1), w - 1)
    _safe_addnstr(stdscr, footer_status_line, 0, clip_text_cells(status_text, w - 1), w - 1, status_attr)

    if footer_help_line != footer_status_line:
        key_hints = "Move: j/k, up/down, pgup/pgdn, g/G,[,] | Open: enter/o, n | Manage: d, v, r, q"
        _safe_addnstr(stdscr, footer_help_line, 0, " " * max(1, w - 1), w - 1)
        _safe_addnstr(stdscr, footer_help_line, 0, clip_text_cells(key_hints, w - 1), w - 1, hint_attr)
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
            if ch == curses.KEY_BACKSPACE or ch == "\b" or ch == "\x7f":
                if chars:
                    chars.pop()
                continue
            if ch == curses.KEY_DC:
                if chars:
                    chars.pop()
                continue
            if isinstance(ch, str) and ch.isprintable():
                chars.append(ch)
    finally:
        curses.curs_set(0)


def run_tui(codex_home: Path) -> tuple[str, dict[str, str] | None]:
    def _inner(stdscr: curses.window) -> tuple[str, dict[str, str] | None]:
        _init_colors()
        curses.curs_set(0)
        stdscr.keypad(True)

        selected_row = 0
        top = 0
        status = ""
        view_mode = VIEW_TIME
        selected_session_id = ""

        while True:
            sessions = collect_sessions(codex_home)
            ordered = sorted_sessions(sessions)
            entries = build_entries(ordered, view_mode)
            selectable = selectable_rows(entries)

            if selectable:
                if selected_session_id:
                    matched = None
                    for i in selectable:
                        s = session_from_entry(entries[i])
                        if s is not None and s.session_id == selected_session_id:
                            matched = i
                            break
                    selected_row = matched if matched is not None else selectable[0]
                elif selected_row not in selectable:
                    selected_row = selectable[0]
            else:
                selected_row = 0
            if selectable:
                s_now = session_from_entry(entries[selected_row])
                if s_now is not None:
                    selected_session_id = s_now.session_id

            top, visible_items = draw_tui(stdscr, entries, selected_row, top, status, view_mode)
            status = ""
            ch = stdscr.getch()

            if ch in (ord("q"), ord("Q")):
                return ("quit", None)
            if ch in (curses.KEY_ENTER, 10, 13, ord("o"), ord("O")):
                if not selectable:
                    status = "No session to resume."
                    continue
                current = session_from_entry(entries[selected_row])
                if current is None:
                    status = "No session to resume."
                    continue
                payload = {"session_id": current.session_id, "cwd": current.cwd or ""}
                return ("resume_bg", payload)
            if ch in (ord("b"), ord("B")):
                status = "Use Enter/o to open selected session as tab."
                continue
            if ch in (ord("n"), ord("N")):
                current = session_from_entry(entries[selected_row]) if selectable else None
                default_dir = current.cwd if current is not None else os.getcwd()
                entered = prompt_input(stdscr, f"New session dir (empty uses {default_dir})")
                if entered is None:
                    status = "New session canceled."
                    continue
                target_dir = entered or default_dir or os.getcwd()
                prompt = prompt_input(stdscr, "Initial prompt (optional)")
                if prompt is None:
                    status = "New session canceled."
                    continue
                payload = {"cwd": target_dir, "prompt": prompt}
                return ("new", payload)
            if ch in (curses.KEY_UP, ord("k"), ord("K")):
                if selectable and selected_row in selectable:
                    pos = selectable.index(selected_row)
                    if pos > 0:
                        selected_row = selectable[pos - 1]
                        s = session_from_entry(entries[selected_row])
                        selected_session_id = s.session_id if s else selected_session_id
                continue
            if ch in (curses.KEY_DOWN, ord("j"), ord("J")):
                if selectable and selected_row in selectable:
                    pos = selectable.index(selected_row)
                    if pos < len(selectable) - 1:
                        selected_row = selectable[pos + 1]
                        s = session_from_entry(entries[selected_row])
                        selected_session_id = s.session_id if s else selected_session_id
                continue
            if ch in (ord("g"),):
                if selectable:
                    selected_row = selectable[0]
                    s = session_from_entry(entries[selected_row])
                    selected_session_id = s.session_id if s else selected_session_id
                continue
            if ch in (ord("G"),):
                if selectable:
                    selected_row = selectable[-1]
                    s = session_from_entry(entries[selected_row])
                    selected_session_id = s.session_id if s else selected_session_id
                continue
            if ch == curses.KEY_HOME:
                if selectable:
                    selected_row = selectable[0]
                    s = session_from_entry(entries[selected_row])
                    selected_session_id = s.session_id if s else selected_session_id
                continue
            if ch == curses.KEY_END:
                if selectable:
                    selected_row = selectable[-1]
                    s = session_from_entry(entries[selected_row])
                    selected_session_id = s.session_id if s else selected_session_id
                continue
            if ch == curses.KEY_PPAGE:
                if selectable and selected_row in selectable:
                    pos = selectable.index(selected_row)
                    pos = max(0, pos - visible_items)
                    selected_row = selectable[pos]
                    s = session_from_entry(entries[selected_row])
                    selected_session_id = s.session_id if s else selected_session_id
                continue
            if ch == curses.KEY_NPAGE:
                if selectable and selected_row in selectable:
                    pos = selectable.index(selected_row)
                    pos = min(len(selectable) - 1, pos + visible_items)
                    selected_row = selectable[pos]
                    s = session_from_entry(entries[selected_row])
                    selected_session_id = s.session_id if s else selected_session_id
                continue
            if ch in (ord("v"), ord("V")):
                idx = VIEW_MODES.index(view_mode)
                view_mode = VIEW_MODES[(idx + 1) % len(VIEW_MODES)]
                top = 0
                status = f"Switched view: {format_view_mode(view_mode)}"
                continue
            if ch == ord("]"):
                ok, msg = switch_tmux_window(next_window=True)
                status = msg if ok else msg
                continue
            if ch == ord("["):
                ok, msg = switch_tmux_window(next_window=False)
                status = msg if ok else msg
                continue
            if ch in (ord("r"), ord("R")):
                status = "Refreshed."
                continue
            if ch in (ord("d"), ord("D"), ord("x"), ord("X"), curses.KEY_DC):
                if not selectable:
                    status = "No session to delete."
                    continue
                current = session_from_entry(entries[selected_row])
                if current is None:
                    status = "No session to delete."
                    continue
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
                selected_session_id = ""
                status = f"Deleted {short_session_id(current.session_id)} (files={removed_files}, index={removed_index})."
                continue

            if selectable and 0 <= selected_row < len(entries):
                current = session_from_entry(entries[selected_row])
                if current is not None:
                    selected_session_id = current.session_id
            status = "Unknown key. Use Up/Down/j/k, Enter/o resume, n new, d delete, v view, r refresh, q quit."

    return curses.wrapper(_inner)
