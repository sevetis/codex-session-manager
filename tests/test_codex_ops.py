from __future__ import annotations

import unittest

from cdx_manager.codex_ops import _parse_tmux_window_rows, _parse_tmux_windows, _window_name_for_session


class CodexOpsTests(unittest.TestCase):
    def test_parse_tmux_windows(self) -> None:
        raw = "0\tCDX Home\t1\t0\n1\trefactor-auth\t0\t1\n2\ts-019da6c8\t0\t\n"
        info = _parse_tmux_windows(raw)
        self.assertIsNotNone(info)
        assert info is not None
        self.assertEqual(info.total, 3)
        self.assertEqual(info.managed, 2)
        self.assertEqual(info.current_index, "0")
        self.assertEqual(info.current_name, "CDX Home")

    def test_parse_tmux_windows_empty(self) -> None:
        self.assertIsNone(_parse_tmux_windows(""))

    def test_window_name_prefers_readable_label(self) -> None:
        name = _window_name_for_session(
            "019da6c7-3f44-7c51-bfae-9d1bcc0867ee",
            "Refactor auth flow!!!",
            "/home/seven/Lab/codex-sess",
        )
        self.assertEqual(name, "refactor-auth-flow")

    def test_parse_tmux_window_rows(self) -> None:
        raw = (
            "@1\t0\tHOME\t\t1\n"
            "@2\t1\trefactor-auth\t019da6c7-3f44-7c51-bfae-9d1bcc0867ee\t0\n"
            "@3\t2\tclean-up\t019da6ad-a9ea-7193-ba0c-416dacd0221e\t0\n"
        )
        rows = _parse_tmux_window_rows(raw)
        self.assertEqual(len(rows), 3)
        self.assertEqual(rows[0].name, "HOME")
        self.assertEqual(rows[1].session_id, "019da6c7-3f44-7c51-bfae-9d1bcc0867ee")
        self.assertEqual(rows[2].window_id, "@3")


if __name__ == "__main__":
    unittest.main()
