#!/usr/bin/env python3
"""Codex session manager and proxy helper.

Features:
- List sessions (from session files + session_index.jsonl)
- Delete by one or more session IDs
- Delete all sessions with --all
- Preview changes with --dry-run
- Resume selected session from TUI
- Create new session with a target directory
"""

from __future__ import annotations

import argparse
import curses
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from pathlib import Path

ID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


@dataclass
class SessionInfo:
    session_id: str
    files: list[Path]
    thread_name: str | None = None
    updated_at: str | None = None
    cwd: str | None = None
    first_prompt: str | None = None


def default_codex_home() -> Path:
    from_env = os.environ.get("CODEX_HOME")
    if from_env:
        return Path(from_env)
    return Path.home() / ".codex"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Codex session manager")
    p.add_argument("session_ids", nargs="*", help="session id(s) to delete")
    p.add_argument("-l", "--list", action="store_true", help="list sessions")
    p.add_argument("--full-id", action="store_true", help="show full id in list header (default shows shortened id)")
    p.add_argument("--new", dest="new_dir", type=Path, help="create a new session in target directory")
    p.add_argument("--prompt", dest="new_prompt", default="", help="optional initial prompt for --new")
    p.add_argument("--all", action="store_true", help="delete all sessions")
    p.add_argument("--dry-run", action="store_true", help="preview only, no changes")
    p.add_argument("-y", "--yes", action="store_true", help="skip confirmation")
    p.add_argument("--codex-home", type=Path, default=default_codex_home(), help="Codex home dir (default: $CODEX_HOME or ~/.codex)")
    p.add_argument("--no-tui", action="store_true", help="disable default interactive TUI mode")
    return p.parse_args()


def collect_sessions(codex_home: Path) -> dict[str, SessionInfo]:
    sessions: dict[str, SessionInfo] = {}
    sessions_root = codex_home / "sessions"
    if sessions_root.exists():
        for fp in sessions_root.rglob("*.jsonl"):
            sid = extract_id_from_filename(fp.name)
            if sid is None:
                continue
            info = sessions.setdefault(sid, SessionInfo(session_id=sid, files=[]))
            info.files.append(fp)

    index_file = codex_home / "session_index.jsonl"
    if index_file.exists():
        with index_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = obj.get("id")
                if not isinstance(sid, str):
                    continue
                info = sessions.setdefault(sid, SessionInfo(session_id=sid, files=[]))
                tn = obj.get("thread_name")
                ua = obj.get("updated_at")
                info.thread_name = tn if isinstance(tn, str) else info.thread_name
                info.updated_at = ua if isinstance(ua, str) else info.updated_at

    for info in sessions.values():
        info.files.sort()
        enrich_from_session_file(info)
    return sessions


def extract_id_from_filename(name: str) -> str | None:
    if not name.endswith(".jsonl"):
        return None
    m = ID_RE.search(name)
    if not m:
        return None
    return m.group(0)


def print_sessions(sessions: dict[str, SessionInfo], full_id: bool = False) -> None:
    if not sessions:
        print("No sessions found.")
        return
    ordered = sorted(
        sessions.values(),
        key=lambda s: (s.updated_at or "", s.session_id),
        reverse=True,
    )
    print(f"Found {len(ordered)} session(s):")
    for idx, s in enumerate(ordered, start=1):
        short_id = short_session_id(s.session_id)
        title = display_title(s)
        header_id = s.session_id if full_id else short_id
        print(f"{idx}. {title}  [{header_id}]")
        print(f"   id: {s.session_id}")
        if s.updated_at:
            print(f"   updated_at: {s.updated_at}")
        if s.cwd:
            print(f"   cwd: {s.cwd}")
        print(f"   files: {len(s.files)}")
        for fp in s.files:
            print(f"   - {fp}")
        print()


def short_session_id(sid: str) -> str:
    return f"{sid[:8]}...{sid[-4:]}"


def display_title(s: SessionInfo) -> str:
    if s.thread_name and s.thread_name.strip():
        return s.thread_name.strip()
    if s.first_prompt and s.first_prompt.strip():
        return clip_text(s.first_prompt.strip(), limit=70)
    return "(untitled)"


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


def is_ignorable_user_text(text: str) -> bool:
    t = text.strip()
    if not t:
        return True
    if t.startswith("<environment_context>") and t.endswith("</environment_context>"):
        return True
    return False


def extract_user_text_from_response_item(obj: dict) -> str | None:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "message" or payload.get("role") != "user":
        return None
    content = payload.get("content")
    if not isinstance(content, list):
        return None
    for part in content:
        if not isinstance(part, dict):
            continue
        if part.get("type") == "input_text":
            txt = part.get("text")
            if isinstance(txt, str) and txt.strip() and not is_ignorable_user_text(txt):
                return txt
    return None


def extract_user_text_from_event_msg(obj: dict) -> str | None:
    payload = obj.get("payload")
    if not isinstance(payload, dict):
        return None
    if payload.get("type") != "user_message":
        return None
    msg = payload.get("message")
    if isinstance(msg, str) and msg.strip() and not is_ignorable_user_text(msg):
        return msg
    return None


def enrich_from_session_file(info: SessionInfo) -> None:
    if not info.files:
        return
    fp = info.files[0]
    try:
        with fp.open("r", encoding="utf-8") as f:
            for line in f:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                rec_type = obj.get("type")
                if rec_type == "session_meta":
                    payload = obj.get("payload")
                    if isinstance(payload, dict):
                        cwd = payload.get("cwd")
                        if isinstance(cwd, str) and cwd.strip():
                            info.cwd = cwd.strip()

                if info.first_prompt is None:
                    text = None
                    if rec_type == "response_item":
                        text = extract_user_text_from_response_item(obj)
                    elif rec_type == "event_msg":
                        text = extract_user_text_from_event_msg(obj)
                    if text:
                        info.first_prompt = text

                if info.cwd and info.first_prompt:
                    break
    except OSError:
        return


def validate_ids(ids: list[str]) -> list[str]:
    valid = []
    bad = []
    for sid in ids:
        if ID_RE.fullmatch(sid):
            valid.append(sid)
        else:
            bad.append(sid)
    if bad:
        print("Invalid session id(s):")
        for sid in bad:
            print(f"- {sid}")
        sys.exit(2)
    return valid


def rewrite_session_index(index_file: Path, delete_ids: set[str], dry_run: bool) -> int:
    if not index_file.exists():
        return 0

    removed = 0
    kept_lines: list[str] = []
    with index_file.open("r", encoding="utf-8") as f:
        for line in f:
            raw = line.rstrip("\n")
            if not raw:
                continue
            try:
                obj = json.loads(raw)
                sid = obj.get("id")
            except json.JSONDecodeError:
                sid = None
            if isinstance(sid, str) and sid in delete_ids:
                removed += 1
                continue
            kept_lines.append(raw)

    if not dry_run:
        tmp = index_file.with_suffix(index_file.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for ln in kept_lines:
                f.write(ln)
                f.write("\n")
        shutil.move(str(tmp), str(index_file))

    return removed


def remove_empty_dirs(root: Path, dry_run: bool) -> None:
    if not root.exists():
        return
    for d in sorted((p for p in root.rglob("*") if p.is_dir()), reverse=True):
        try:
            next(d.iterdir())
            is_empty = False
        except StopIteration:
            is_empty = True
        if is_empty and not dry_run:
            d.rmdir()


def execute_delete(codex_home: Path, sessions: dict[str, SessionInfo], target_ids: set[str], dry_run: bool) -> tuple[int, int, list[Path]]:
    matched_ids = sorted(sid for sid in target_ids if sid in sessions)
    files_to_delete: list[Path] = []
    for sid in matched_ids:
        files_to_delete.extend(sessions[sid].files)

    if dry_run:
        removed_index = rewrite_session_index(codex_home / "session_index.jsonl", target_ids, dry_run=True)
        return (0, removed_index, files_to_delete)

    removed_files = 0
    for fp in files_to_delete:
        if fp.exists():
            fp.unlink()
            removed_files += 1

    removed_index = rewrite_session_index(codex_home / "session_index.jsonl", target_ids, dry_run=False)
    remove_empty_dirs(codex_home / "sessions", dry_run=False)
    return (removed_files, removed_index, files_to_delete)


def sorted_sessions(sessions: dict[str, SessionInfo]) -> list[SessionInfo]:
    return sorted(
        sessions.values(),
        key=lambda s: (s.updated_at or "", s.session_id),
        reverse=True,
    )


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
    curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_CYAN)   # selected row
    curses.init_pair(2, curses.COLOR_BLACK, curses.COLOR_WHITE)  # header
    curses.init_pair(3, curses.COLOR_CYAN, -1)                   # section title
    curses.init_pair(4, curses.COLOR_YELLOW, -1)                 # status
    curses.init_pair(5, curses.COLOR_GREEN, -1)                  # hint


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


def run_codex_resume(session_id: str, cwd: str | None) -> int:
    cmd = ["codex", "resume", session_id]
    run_cwd = cwd if cwd and Path(cwd).exists() else None
    where = run_cwd or os.getcwd()
    print(f"Launching: {' '.join(cmd)} (cwd={where})")
    try:
        completed = subprocess.run(cmd, cwd=run_cwd, check=False)
    except FileNotFoundError:
        print("Failed: `codex` command not found in PATH.")
        return 127
    return completed.returncode


def run_codex_new(target_dir: str | Path, prompt: str = "") -> int:
    target = Path(target_dir).expanduser()
    cmd = ["codex", "-C", str(target)]
    if prompt.strip():
        cmd.append(prompt.strip())
    run_cwd = str(target) if target.exists() else os.getcwd()
    where = run_cwd or os.getcwd()
    print(f"Launching: {' '.join(cmd)} (cwd={where})")
    try:
        completed = subprocess.run(cmd, cwd=run_cwd, check=False)
    except FileNotFoundError:
        print("Failed: `codex` command not found in PATH.")
        return 127
    return completed.returncode


def main() -> int:
    args = parse_args()
    codex_home: Path = args.codex_home.expanduser()

    if args.new_dir is not None:
        return run_codex_new(args.new_dir, args.new_prompt)

    if not args.no_tui and not args.list and not args.all and not args.session_ids:
        try:
            action, payload = run_tui(codex_home)
            if action == "resume" and payload is not None:
                return run_codex_resume(payload.get("session_id", ""), payload.get("cwd", ""))
            if action == "new" and payload is not None:
                return run_codex_new(payload.get("cwd", ""), payload.get("prompt", ""))
            return 0
        except curses.error:
            print("TUI could not start in this terminal. Try --list or run in a real TTY.")
            return 1

    sessions = collect_sessions(codex_home)

    if args.list:
        print_sessions(sessions, full_id=args.full_id)
        if not args.all and not args.session_ids:
            return 0

    if not args.all and not args.session_ids:
        print("Nothing to delete. Use --list, --all, or provide session id(s).")
        return 1

    if args.all:
        target_ids = set(sessions.keys())
    else:
        target_ids = set(validate_ids(args.session_ids))

    if not target_ids:
        print("No matching sessions to delete.")
        return 0

    missing = sorted(sid for sid in target_ids if sid not in sessions)
    if missing:
        print("Warning: session id(s) not found in current data:")
        for sid in missing:
            print(f"- {sid}")

    matched_ids = sorted(sid for sid in target_ids if sid in sessions)
    if not matched_ids:
        print("No existing session files matched. Will still clean matching entries in session_index.jsonl if any.")

    files_to_delete: list[Path] = []
    for sid in matched_ids:
        files_to_delete.extend(sessions[sid].files)

    print("Planned actions:")
    print(f"- delete session IDs: {len(target_ids)}")
    print(f"- delete files: {len(files_to_delete)}")
    for fp in files_to_delete:
        print(f"    {fp}")

    if args.dry_run:
        _removed_files, removed_index, _planned = execute_delete(
            codex_home=codex_home,
            sessions=sessions,
            target_ids=target_ids,
            dry_run=True,
        )
        print(f"- session_index entries to remove: {removed_index}")
        print("Dry-run only, no files changed.")
        return 0

    if not args.yes:
        reply = input("Proceed? Type 'yes' to continue: ").strip().lower()
        if reply != "yes":
            print("Aborted.")
            return 1

    removed_files, removed_index, _planned = execute_delete(
        codex_home=codex_home,
        sessions=sessions,
        target_ids=target_ids,
        dry_run=False,
    )

    print("Done.")
    print(f"- removed files: {removed_files}")
    print(f"- removed session_index entries: {removed_index}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
