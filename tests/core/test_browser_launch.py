"""Tests for browser app-mode launch flags."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.core.platform import browser


class BrowserLaunchTests(unittest.TestCase):
    def test_seed_app_profile_disables_translation_and_sets_language_order(self) -> None:
        with tempfile.TemporaryDirectory() as profile_dir:
            browser._seed_app_profile(profile_dir)

            preferences = json.loads(
                (Path(profile_dir) / "Default" / "Preferences").read_text(
                    encoding="utf-8"
                )
            )

        self.assertFalse(preferences["translate"]["enabled"])
        self.assertEqual(preferences["intl"]["accept_languages"], "de,en-US,en")

    def test_seed_app_profile_preserves_unrelated_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as profile_dir:
            profile = Path(profile_dir) / "Default"
            profile.mkdir()
            (profile / "Preferences").write_text(
                json.dumps({"profile": {"name": "LLNG"}}), encoding="utf-8"
            )

            browser._seed_app_profile(profile_dir)

            preferences = json.loads((profile / "Preferences").read_text(encoding="utf-8"))

        self.assertEqual(preferences["profile"]["name"], "LLNG")

    def test_frontend_declares_german_default_and_blocks_browser_shortcuts(self) -> None:
        html = Path("src/frontend/app/index.html").read_text(encoding="utf-8")
        app_js = Path("src/frontend/app/app.js").read_text(encoding="utf-8")

        self.assertIn('<html lang="de">', html)
        self.assertIn('event.key === "F11"', app_js)
        self.assertIn('event.key === "F12"', app_js)
        self.assertIn('event.ctrlKey && key === "u"', app_js)
        self.assertIn('"keydown",', app_js)

    def test_windows_launch_uses_app_mode_start_maximized_and_new_window(self) -> None:
        with (
            patch(
                "src.core.platform.browser.find_browser_executable",
                return_value="C:/Browser/browser.exe",
            ),
            patch.object(browser.sys, "platform", "win32"),
            patch("src.core.platform.browser.subprocess.Popen") as mocked_popen,
        ):
            handle = browser.open_browser_app_mode("http://127.0.0.1:8090/")

        self.assertIsNotNone(handle)
        args, kwargs = mocked_popen.call_args
        launch_args = args[0]
        self.assertGreaterEqual(len(launch_args), 5)
        self.assertEqual(launch_args[0], "C:/Browser/browser.exe")
        self.assertEqual(launch_args[1], "--app=http://127.0.0.1:8090/")
        self.assertEqual(launch_args[2], "--start-maximized")
        self.assertEqual(launch_args[3], "--new-window")
        self.assertIn("--no-first-run", launch_args)
        self.assertIn("--no-default-browser-check", launch_args)
        self.assertIn("--disable-search-engine-choice-screen", launch_args)
        self.assertIn("--lang=de", launch_args)
        self.assertTrue(
            any(arg.startswith("--user-data-dir=") for arg in launch_args),
        )
        self.assertEqual(kwargs, {})

    def test_linux_launch_uses_app_mode_start_new_session_and_start_maximized(
        self,
    ) -> None:
        with (
            patch(
                "src.core.platform.browser.find_browser_executable",
                return_value="/usr/bin/chromium",
            ),
            patch.object(browser.sys, "platform", "linux"),
            patch("src.core.platform.browser.subprocess.Popen") as mocked_popen,
        ):
            handle = browser.open_browser_app_mode("http://127.0.0.1:8090/")

        self.assertIsNotNone(handle)
        args, kwargs = mocked_popen.call_args
        launch_args = args[0]
        self.assertGreaterEqual(len(launch_args), 5)
        self.assertEqual(launch_args[0], "/usr/bin/chromium")
        self.assertEqual(launch_args[1], "--app=http://127.0.0.1:8090/")
        self.assertEqual(launch_args[2], "--start-maximized")
        self.assertEqual(launch_args[3], "--new-window")
        self.assertIn("--no-first-run", launch_args)
        self.assertIn("--no-default-browser-check", launch_args)
        self.assertIn("--disable-search-engine-choice-screen", launch_args)
        self.assertIn("--lang=de", launch_args)
        self.assertTrue(
            any(arg.startswith("--user-data-dir=") for arg in launch_args),
        )
        self.assertEqual(kwargs, {"start_new_session": True})

    def test_fallback_to_default_browser_when_app_mode_launch_fails(self) -> None:
        with (
            patch(
                "src.core.platform.browser.find_browser_executable",
                return_value="/usr/bin/chromium",
            ),
            patch.object(browser.sys, "platform", "linux"),
            patch(
                "src.core.platform.browser.subprocess.Popen",
                side_effect=OSError("failed"),
            ),
            patch("src.core.platform.browser.webbrowser.open") as mocked_open,
        ):
            handle = browser.open_browser_app_mode("http://127.0.0.1:8090/")

        self.assertIsNone(handle)
        mocked_open.assert_called_once_with("http://127.0.0.1:8090/")

    def test_launch_ui_async_wires_close_monitor_when_handle_exists(self) -> None:
        handle = browser.BrowserLaunchHandle(process=Mock(), profile_dir="tmp")
        callback = Mock()
        with (
            patch(
                "src.core.platform.browser.open_browser_app_mode", return_value=handle
            ),
            patch("src.core.platform.browser._monitor_browser_close") as mocked_monitor,
            patch("src.core.platform.browser.time.sleep"),
            patch("src.core.platform.browser.Thread") as mocked_thread,
        ):
            mocked_thread.side_effect = lambda *args, **kwargs: Mock(
                start=lambda: kwargs["target"]()
            )
            browser.launch_ui_async("http://127.0.0.1:8090/", on_closed=callback)
        mocked_monitor.assert_called_once_with(handle, callback)

    def test_monitor_browser_close_invokes_callback_after_min_runtime(self) -> None:
        process = Mock()
        process.wait = Mock()
        handle = browser.BrowserLaunchHandle(process=process, profile_dir=None)
        callback = Mock()

        class ImmediateThread:
            def __init__(self, target, daemon):
                self._target = target

            def start(self):
                self._target()

        with (
            patch("src.core.platform.browser.Thread", ImmediateThread),
            patch("src.core.platform.browser.time.monotonic", side_effect=[0.0, 2.0]),
        ):
            browser._monitor_browser_close(handle, callback, min_runtime_seconds=1.0)
        callback.assert_called_once()

    def test_close_browser_app_mode_terminates_active_handle(self) -> None:
        process = Mock()
        process.poll = Mock(side_effect=[None, None, 0, 0])
        process.terminate = Mock()
        process.kill = Mock()
        handle = browser.BrowserLaunchHandle(process=process, profile_dir="tmp")
        with (
            patch.object(browser, "_active_browser_handle", handle),
            patch("src.core.platform.browser.shutil.rmtree") as mocked_rmtree,
            patch(
                "src.core.platform.browser.time.monotonic",
                side_effect=[0.0, 0.0, 0.1],
            ),
            patch("src.core.platform.browser.time.sleep"),
        ):
            closed = browser.close_browser_app_mode(timeout_seconds=0.2)
        self.assertTrue(closed)
        process.terminate.assert_called_once()
        process.kill.assert_not_called()
        mocked_rmtree.assert_called_once_with("tmp", ignore_errors=True)
        self.assertIsNone(browser._active_browser_handle)  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
