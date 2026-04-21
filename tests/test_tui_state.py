from __future__ import annotations

import unittest
from pathlib import Path

from cdx_manager.models import SessionInfo
from cdx_manager.tui_state import VIEW_CWD, VIEW_TIME, build_entries, selectable_rows


class TuiStateTests(unittest.TestCase):
    def _session(self, sid: str, cwd: str, updated: str) -> SessionInfo:
        return SessionInfo(session_id=sid, files=[Path(f"/tmp/{sid}.jsonl")], cwd=cwd, updated_at=updated)

    def test_time_view_contains_only_sessions(self) -> None:
        sessions = [
            self._session("019da6c7-3f44-7c51-bfae-9d1bcc0867ee", "/a", "2026-04-20T10:00:00Z"),
            self._session("019da6c7-3f44-7c51-bfae-9d1bcc0867ef", "/b", "2026-04-19T10:00:00Z"),
        ]
        entries = build_entries(sessions, VIEW_TIME)
        self.assertEqual(len(entries), 2)
        self.assertEqual([e.type for e in entries], ["session", "session"])
        self.assertEqual(selectable_rows(entries), [0, 1])

    def test_cwd_view_groups_and_inserts_headers(self) -> None:
        sessions = [
            self._session("019da6c7-3f44-7c51-bfae-9d1bcc0867ee", "/repo/a", "2026-04-20T10:00:00Z"),
            self._session("019da6c7-3f44-7c51-bfae-9d1bcc0867ef", "/repo/a", "2026-04-19T10:00:00Z"),
            self._session("019da6c7-3f44-7c51-bfae-9d1bcc0867f0", "/repo/b", "2026-04-18T10:00:00Z"),
        ]
        entries = build_entries(sessions, VIEW_CWD)
        self.assertEqual(entries[0].type, "header")
        self.assertEqual(entries[1].type, "session")
        self.assertIn("/repo/a", entries[0].title)
        self.assertEqual(len(selectable_rows(entries)), 3)


if __name__ == "__main__":
    unittest.main()
