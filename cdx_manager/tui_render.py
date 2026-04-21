from __future__ import annotations

import curses

from .models import SessionInfo
from .textutil import char_cell_width, clip_text_cells, display_title, pad_text_cells, short_session_id, text_cell_width
from .tui_state import SessionEntry, format_view_mode, selectable_rows, session_from_entry


def safe_addnstr(stdscr: curses.window, y: int, x: int, text: str, max_len: int, attr: int = 0) -> None:
    if max_len <= 0:
        return
    try:
        stdscr.addnstr(y, x, text, max_len, attr)
    except curses.error:
        return


def init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)
    curses.init_pair(2, curses.COLOR_YELLOW, curses.COLOR_BLACK)
    curses.init_pair(3, curses.COLOR_CYAN, -1)
    curses.init_pair(4, curses.COLOR_YELLOW, -1)
    curses.init_pair(5, curses.COLOR_GREEN, -1)
    curses.init_pair(6, curses.COLOR_BLUE, -1)
    curses.init_pair(7, curses.COLOR_WHITE, -1)
    curses.init_pair(8, curses.COLOR_BLUE, -1)


def detail_lines(session: SessionInfo | None) -> list[tuple[str, str] | str]:
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


def wrap_text_cells(text: str, max_cells: int, max_lines: int) -> list[str]:
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

    original_width = text_cell_width(src)
    visible_width = sum(text_cell_width(x) for x in lines)
    if visible_width < original_width and lines:
        lines[-1] = clip_text_cells(lines[-1], max_cells)
    return lines[:max_lines] if lines else [""]


def draw_panel_border(stdscr: curses.window, top: int, left: int, height: int, width: int) -> None:
    if height < 2 or width < 2:
        return
    right = left + width - 1
    bottom = top + height - 1
    for x in range(left + 1, right):
        safe_addnstr(stdscr, top, x, "-", 1)
        safe_addnstr(stdscr, bottom, x, "-", 1)
    for y in range(top + 1, bottom):
        safe_addnstr(stdscr, y, left, "|", 1)
        safe_addnstr(stdscr, y, right, "|", 1)
    safe_addnstr(stdscr, top, left, "+", 1)
    safe_addnstr(stdscr, top, right, "+", 1)
    safe_addnstr(stdscr, bottom, left, "+", 1)
    safe_addnstr(stdscr, bottom, right, "+", 1)


def draw_tui(
    stdscr: curses.window,
    entries: list[SessionEntry],
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

    selectable = selectable_rows(entries)
    selected_pos = selectable.index(selected_row) + 1 if selected_row in selectable else 0
    summary = f"Total: {len(selectable)}  View: {format_view_mode(view_mode)}"
    if selectable:
        summary += f"  Selected: {selected_pos}/{len(selectable)}"
    safe_addnstr(stdscr, 0, 0, " " * max(1, w - 1), w - 1, header_attr)
    safe_addnstr(stdscr, 0, 2, clip_text_cells(summary, w - 4), w - 4, hint_attr)

    content_top = 1
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

    left_top, left_left, left_height, left_width = content_top, 0, content_height, max(1, left_w)
    if split:
        right_top, right_left = content_top, left_w + 1
        right_height, right_width = content_height, max(1, right_w)
        draw_panel_border(stdscr, right_top, right_left, right_height, right_width)
        safe_addnstr(stdscr, right_top, right_left + 2, "Details", right_width - 4, section_attr)

    list_inner_top, list_inner_left = left_top, left_left
    list_inner_height, list_inner_width = left_height, left_width
    if split:
        draw_panel_border(stdscr, left_top, left_left, left_height, left_width)
        safe_addnstr(stdscr, left_top, left_left + 2, "Sessions", left_width - 4, section_attr)
        list_inner_top += 1
        list_inner_left += 1
        list_inner_height -= 2
        list_inner_width -= 2

    visible_items = max(1, list_inner_height)
    if selected_row < top:
        top = selected_row
    if selected_row >= top + visible_items:
        top = selected_row - visible_items + 1

    for row_idx in range(visible_items):
        idx = top + row_idx
        if idx >= len(entries):
            break
        entry = entries[idx]
        y = list_inner_top + row_idx

        if entry.type == "header":
            header = f"[{clip_text_cells(entry.title, max(6, list_inner_width - 2))}]"
            safe_addnstr(stdscr, y, list_inner_left, header, list_inner_width, group_header_attr)
            continue

        session = session_from_entry(entry)
        if session is None:
            continue

        marker = ">" if idx == selected_row else " "
        id_text = short_session_id(session.session_id)
        title_max = max(12, min(38, list_inner_width // 2))
        title_col = pad_text_cells(display_title(session), title_max)
        id_col_text = pad_text_cells(id_text, 14)
        used_cells = 2 + title_max + 2 + 14 + 2
        cwd_max = max(6, list_inner_width - used_cells)
        cwd_text = clip_text_cells(session.cwd or "-", cwd_max)
        line = f"{marker} {title_col}  {id_col_text}  {cwd_text}"
        attr = selected_attr if idx == selected_row else curses.A_NORMAL
        safe_addnstr(stdscr, y, list_inner_left, line, list_inner_width, attr)

    if split:
        current = session_from_entry(entries[selected_row]) if entries and 0 <= selected_row < len(entries) else None
        rows = detail_lines(current)
        start_y, start_x = content_top + 1, left_w + 2
        max_h, max_w = max(1, content_height - 2), max(1, right_w - 2)
        y_off = 0

        for row in rows:
            if y_off >= max_h:
                break
            y = start_y + y_off

            if isinstance(row, str):
                if row:
                    safe_addnstr(stdscr, y, start_x, clip_text_cells(row, max_w), max_w, detail_key_attr)
                y_off += 1
                continue

            key, value = row
            if key == "first_prompt":
                safe_addnstr(stdscr, y, start_x, "first_prompt", max_w, detail_key_attr)
                y_off += 1
                if y_off >= max_h:
                    break
                val_x, val_w = start_x + 2, max(1, max_w - 2)
                for cont in wrap_text_cells(value.strip(), val_w, max_h - y_off):
                    if y_off >= max_h:
                        break
                    safe_addnstr(stdscr, start_y + y_off, val_x, cont, val_w, detail_val_attr)
                    y_off += 1
                continue

            if key == "session_file":
                val_x, val_w = start_x + 2, max(1, max_w - 2)
                for cont in wrap_text_cells(value.strip(), val_w, max_h - y_off):
                    if y_off >= max_h:
                        break
                    safe_addnstr(stdscr, start_y + y_off, val_x, cont, val_w, detail_val_attr)
                    y_off += 1
                continue

            key_text = f"{key:<12}" if key else " " * 12
            key_cells = min(max_w, len(key_text) + 1)
            val_w = max(1, max_w - key_cells)
            wrapped = wrap_text_cells(value.strip(), val_w, max_h - y_off) or [""]

            safe_addnstr(stdscr, y, start_x, key_text, key_cells, detail_key_attr)
            safe_addnstr(stdscr, y, start_x + key_cells, wrapped[0], val_w, detail_val_attr)
            y_off += 1
            for cont in wrapped[1:]:
                if y_off >= max_h:
                    break
                yy = start_y + y_off
                safe_addnstr(stdscr, yy, start_x, " " * key_cells, key_cells, detail_key_attr)
                safe_addnstr(stdscr, yy, start_x + key_cells, cont, val_w, detail_val_attr)
                y_off += 1

    status_text = f"Status: {status}" if status else "Status: idle"
    safe_addnstr(stdscr, footer_status_line, 0, " " * max(1, w - 1), w - 1)
    safe_addnstr(stdscr, footer_status_line, 0, clip_text_cells(status_text, w - 1), w - 1, status_attr)

    if footer_help_line != footer_status_line:
        key_hints = "Move: j/k, up/down, pgup/pgdn, g/G,[,] | Open: enter/o, n | Manage: d, v, r, q"
        safe_addnstr(stdscr, footer_help_line, 0, " " * max(1, w - 1), w - 1)
        safe_addnstr(stdscr, footer_help_line, 0, clip_text_cells(key_hints, w - 1), w - 1, hint_attr)

    stdscr.refresh()
    return top, visible_items
