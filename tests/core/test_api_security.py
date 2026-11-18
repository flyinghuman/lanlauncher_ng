"""Security tests for API network exposure guards."""

from __future__ import annotations

import unittest

from src.core.api.server import _is_client_disconnect_error, _is_loopback_address


class ApiSecurityTests(unittest.TestCase):
    def test_loopback_addresses_allowed(self) -> None:
        self.assertTrue(_is_loopback_address("127.0.0.1"))
        self.assertTrue(_is_loopback_address("::1"))
        self.assertTrue(_is_loopback_address("localhost"))
        self.assertTrue(_is_loopback_address(" LOCALHOST "))

    def test_non_loopback_addresses_rejected(self) -> None:
        self.assertFalse(_is_loopback_address(None))
        self.assertFalse(_is_loopback_address(""))
        self.assertFalse(_is_loopback_address("0.0.0.0"))
        self.assertFalse(_is_loopback_address("192.168.1.11"))
        self.assertFalse(_is_loopback_address("10.0.0.5"))

    def test_client_disconnect_errors_detected(self) -> None:
        self.assertTrue(_is_client_disconnect_error(BrokenPipeError()))
        self.assertTrue(_is_client_disconnect_error(ConnectionResetError()))
        self.assertTrue(_is_client_disconnect_error(ConnectionAbortedError()))
        win_abort = OSError("aborted")
        win_abort.winerror = 10053  # type: ignore[attr-defined]
        self.assertTrue(_is_client_disconnect_error(win_abort))
        other = OSError("other")
        other.winerror = 5  # type: ignore[attr-defined]
        self.assertFalse(_is_client_disconnect_error(other))


if __name__ == "__main__":
    unittest.main()
