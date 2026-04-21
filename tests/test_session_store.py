from __future__ import annotations

import unittest

from cdx_manager.session_store import InvalidSessionIdsError, validate_ids


class SessionStoreTests(unittest.TestCase):
    def test_validate_ids_returns_valid(self) -> None:
        sid = "019da6c7-3f44-7c51-bfae-9d1bcc0867ee"
        self.assertEqual(validate_ids([sid]), [sid])

    def test_validate_ids_raises_on_invalid(self) -> None:
        with self.assertRaises(InvalidSessionIdsError) as ctx:
            validate_ids(["bad-id"])
        self.assertEqual(ctx.exception.bad_ids, ["bad-id"])


if __name__ == "__main__":
    unittest.main()
