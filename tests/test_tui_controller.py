from __future__ import annotations

import unittest
from pathlib import Path

from cdx_manager.models import SessionInfo
from cdx_manager.tui_controller import dispatch_key, sync_selection
from cdx_manager.tui_state import SessionEntry, UiState, VIEW_CWD, VIEW_TIME


class DummyRepo:
    def __init__(self) -> None:
        self.codex_home = Path("/tmp")
        self.sessions = {}


class TuiControllerTests(unittest.TestCase):
    def _entries(self) -> list[SessionEntry]:
        s1 = SessionInfo(session_id="019da6c7-3f44-7c51-bfae-9d1bcc0867ee", files=[])
        s2 = SessionInfo(session_id="019da6c7-3f44-7c51-bfae-9d1bcc0867ef", files=[])
        return [
            SessionEntry(type="header", title="/a (2)"),
            SessionEntry(type="session", session=s1),
            SessionEntry(type="session", session=s2),
        ]

    def test_sync_selection_selects_first_session_row(self) -> None:
        state = UiState()
        selectable = sync_selection(self._entries(), state)
        self.assertEqual(selectable, [1, 2])
        self.assertEqual(state.selected_row, 1)

    def test_dispatch_navigation_and_jump(self) -> None:
        state = UiState(selected_row=1)
        entries = self._entries()
        selectable = [1, 2]
        repo = DummyRepo()

        dispatch_key(None, ord("j"), entries, selectable, 5, state, repo)
        self.assertEqual(state.selected_row, 2)

        dispatch_key(None, ord("k"), entries, selectable, 5, state, repo)
        self.assertEqual(state.selected_row, 1)

        dispatch_key(None, ord("G"), entries, selectable, 5, state, repo)
        self.assertEqual(state.selected_row, 2)

        dispatch_key(None, ord("g"), entries, selectable, 5, state, repo)
        self.assertEqual(state.selected_row, 1)

    def test_dispatch_view_toggle_refresh_and_quit(self) -> None:
        state = UiState(view_mode=VIEW_CWD)
        entries = self._entries()
        selectable = [1, 2]
        repo = DummyRepo()

        res = dispatch_key(None, ord("v"), entries, selectable, 5, state, repo)
        self.assertEqual(res.action, "continue")
        self.assertEqual(state.view_mode, VIEW_TIME)

        res = dispatch_key(None, ord("r"), entries, selectable, 5, state, repo)
        self.assertTrue(res.needs_refresh)

        res = dispatch_key(None, ord("q"), entries, selectable, 5, state, repo)
        self.assertEqual(res.action, "quit")


if __name__ == "__main__":
    unittest.main()
