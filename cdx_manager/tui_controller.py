from __future__ import annotations

import curses
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .codex_ops import close_tmux_tabs_for_session, run_codex_resume_background, switch_tmux_window
from .models import SessionInfo
from .session_store import execute_delete
from .textutil import clip_text, display_title, short_session_id
from .tui_input import confirm_delete, prompt_input
from .tui_state import VIEW_MODES, SessionEntry, UiState, format_view_mode, selectable_rows, session_from_entry


class SessionRepo(Protocol):
    codex_home: Path
    sessions: dict[str, SessionInfo]


@dataclass(frozen=True)
class DispatchResult:
    action: str = "continue"
    payload: dict[str, str] | None = None
    needs_refresh: bool = False


def sync_selection(entries: list[SessionEntry], state: UiState) -> list[int]:
    selectable = selectable_rows(entries)
    if selectable:
        if state.selected_session_id:
            matched = None
            for i in selectable:
                s = session_from_entry(entries[i])
                if s is not None and s.session_id == state.selected_session_id:
                    matched = i
                    break
            state.selected_row = matched if matched is not None else selectable[0]
        elif state.selected_row not in selectable:
            state.selected_row = selectable[0]
    else:
        state.selected_row = 0

    if selectable:
        current = session_from_entry(entries[state.selected_row])
        if current is not None:
            state.selected_session_id = current.session_id
    return selectable


def _move_selection(selectable: list[int], state: UiState, delta: int) -> None:
    if not selectable or state.selected_row not in selectable:
        return
    pos = selectable.index(state.selected_row)
    pos = max(0, min(len(selectable) - 1, pos + delta))
    state.selected_row = selectable[pos]


def _set_selection(selectable: list[int], state: UiState, pos: int) -> None:
    if not selectable:
        return
    pos = max(0, min(len(selectable) - 1, pos))
    state.selected_row = selectable[pos]


def _update_selected_session_id(entries: list[SessionEntry], state: UiState) -> None:
    current = _current_session(entries, state)
    if current is not None:
        state.selected_session_id = current.session_id


def _current_session(entries: list[SessionEntry], state: UiState) -> SessionInfo | None:
    if not entries or state.selected_row < 0 or state.selected_row >= len(entries):
        return None
    return session_from_entry(entries[state.selected_row])


def _handle_open(entries: list[SessionEntry], selectable: list[int], state: UiState) -> DispatchResult:
    if not selectable:
        state.status = "No session to resume."
        return DispatchResult()
    current = _current_session(entries, state)
    if current is None:
        state.status = "No session to resume."
        return DispatchResult()
    ok, msg = run_codex_resume_background(
        current.session_id,
        current.cwd or "",
        tab_label=display_title(current),
    )
    state.status = msg if ok else msg
    return DispatchResult()


def _handle_new(stdscr: curses.window, entries: list[SessionEntry], selectable: list[int], state: UiState) -> DispatchResult:
    current = _current_session(entries, state) if selectable else None
    default_dir = current.cwd if current is not None else os.getcwd()
    entered = prompt_input(stdscr, f"New session dir (empty uses {default_dir})")
    if entered is None:
        state.status = "New session canceled."
        return DispatchResult()

    target_dir = entered or default_dir or os.getcwd()
    prompt = prompt_input(stdscr, "Initial prompt (optional)")
    if prompt is None:
        state.status = "New session canceled."
        return DispatchResult()

    payload = {"cwd": target_dir, "prompt": prompt}
    return DispatchResult(action="new", payload=payload)


def _handle_delete(stdscr: curses.window, repo: SessionRepo, entries: list[SessionEntry], selectable: list[int], state: UiState) -> DispatchResult:
    if not selectable:
        state.status = "No session to delete."
        return DispatchResult()
    current = _current_session(entries, state)
    if current is None:
        state.status = "No session to delete."
        return DispatchResult()

    ok = confirm_delete(
        stdscr,
        "\n".join(
            [
                "Delete this session?",
                f"title: {clip_text(display_title(current), 56)}",
                f"id: {short_session_id(current.session_id)}",
                f"cwd: {clip_text(current.cwd or '-', 56)}",
            ]
        ),
    )
    if not ok:
        state.status = "Delete canceled."
        return DispatchResult()

    close_ok, close_msg = close_tmux_tabs_for_session(current.session_id)
    removed_files, removed_index, _ = execute_delete(
        codex_home=repo.codex_home,
        sessions=repo.sessions,
        target_ids={current.session_id},
        dry_run=False,
    )
    state.selected_session_id = ""
    close_note = ""
    if close_ok and "Closed " in close_msg:
        close_note = f", {close_msg.lower()}"
    state.status = (
        f"Deleted {short_session_id(current.session_id)} "
        f"(files={removed_files}, index={removed_index}{close_note})."
    )
    return DispatchResult(needs_refresh=True)


def dispatch_key(
    stdscr: curses.window,
    ch: int,
    entries: list[SessionEntry],
    selectable: list[int],
    visible_items: int,
    state: UiState,
    repo: SessionRepo,
) -> DispatchResult:
    if ch in (ord("q"), ord("Q")):
        return DispatchResult(action="quit")
    if ch in (curses.KEY_ENTER, 10, 13, ord("o"), ord("O")):
        return _handle_open(entries, selectable, state)
    if ch in (ord("n"), ord("N")):
        return _handle_new(stdscr, entries, selectable, state)
    if ch in (curses.KEY_UP, ord("k"), ord("K")):
        _move_selection(selectable, state, -1)
        _update_selected_session_id(entries, state)
        return DispatchResult()
    if ch in (curses.KEY_DOWN, ord("j"), ord("J")):
        _move_selection(selectable, state, 1)
        _update_selected_session_id(entries, state)
        return DispatchResult()
    if ch in (ord("g"), curses.KEY_HOME):
        _set_selection(selectable, state, 0)
        _update_selected_session_id(entries, state)
        return DispatchResult()
    if ch in (ord("G"), curses.KEY_END):
        _set_selection(selectable, state, len(selectable) - 1)
        _update_selected_session_id(entries, state)
        return DispatchResult()
    if ch == curses.KEY_PPAGE:
        if selectable and state.selected_row in selectable:
            pos = selectable.index(state.selected_row)
            _set_selection(selectable, state, pos - visible_items)
            _update_selected_session_id(entries, state)
        return DispatchResult()
    if ch == curses.KEY_NPAGE:
        if selectable and state.selected_row in selectable:
            pos = selectable.index(state.selected_row)
            _set_selection(selectable, state, pos + visible_items)
            _update_selected_session_id(entries, state)
        return DispatchResult()
    if ch in (ord("v"), ord("V")):
        idx = VIEW_MODES.index(state.view_mode)
        state.view_mode = VIEW_MODES[(idx + 1) % len(VIEW_MODES)]
        state.top = 0
        state.status = f"Switched view: {format_view_mode(state.view_mode)}"
        return DispatchResult()
    if ch == ord("]"):
        ok, msg = switch_tmux_window(next_window=True)
        state.status = msg if ok else msg
        return DispatchResult()
    if ch == ord("["):
        ok, msg = switch_tmux_window(next_window=False)
        state.status = msg if ok else msg
        return DispatchResult()
    if ch in (ord("r"), ord("R")):
        state.status = "Refreshed."
        return DispatchResult(needs_refresh=True)
    if ch in (ord("d"), ord("D"), ord("x"), ord("X"), curses.KEY_DC):
        return _handle_delete(stdscr, repo, entries, selectable, state)

    current = _current_session(entries, state)
    if current is not None:
        state.selected_session_id = current.session_id
    state.status = "Unknown key. Use Up/Down/j/k, Enter/o resume, n new, d delete, v view, r refresh, q quit."
    return DispatchResult()
