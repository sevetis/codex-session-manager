from __future__ import annotations

import curses
from pathlib import Path

from .codex_ops import close_managed_tmux_tabs
from .tui_controller import dispatch_key, sync_selection
from .tui_render import draw_tui, init_colors
from .tui_repo import SessionRepository
from .tui_state import UiState, build_entries


def run_tui(codex_home: Path) -> tuple[str, dict[str, str] | None]:
    def _inner(stdscr: curses.window) -> tuple[str, dict[str, str] | None]:
        init_colors()
        curses.curs_set(0)
        stdscr.keypad(True)

        repo = SessionRepository.create(codex_home)
        state = UiState()
        needs_refresh = False

        while True:
            if needs_refresh:
                repo.refresh()
                needs_refresh = False

            entries = build_entries(repo.ordered(), state.view_mode)
            selectable = sync_selection(entries, state)
            state.top, visible_items = draw_tui(
                stdscr,
                entries,
                state.selected_row,
                state.top,
                state.status,
                state.view_mode,
            )
            state.status = ""
            ch = stdscr.getch()

            result = dispatch_key(
                stdscr=stdscr,
                ch=ch,
                entries=entries,
                selectable=selectable,
                visible_items=visible_items,
                state=state,
                repo=repo,
            )
            if result.action == "quit":
                close_managed_tmux_tabs()
                return ("quit", None)
            if result.action == "new":
                return ("new", result.payload)
            if result.needs_refresh:
                needs_refresh = True

    return curses.wrapper(_inner)
