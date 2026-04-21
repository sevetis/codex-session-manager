from __future__ import annotations

import unittest

from cdx_manager.codex_ops import _parse_tmux_windows, _window_name_for_session


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


if __name__ == "__main__":
    unittest.main()
