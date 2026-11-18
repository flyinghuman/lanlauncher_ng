"""Browser launch support for App Mode."""

from __future__ import annotations

import os
import json
import shutil
import subprocess
import sys
import tempfile
import time
import webbrowser
from dataclasses import dataclass
from pathlib import Path
from threading import Thread
from threading import Lock
from typing import Callable


def find_browser_executable() -> str | None:
    if sys.platform == "win32":
        paths = [
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
            r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
            os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
            r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
            r"C:\Program Files (x86)\BraveSoftware\Brave-Browser\Application\brave.exe",
        ]
        for p in paths:
            if os.path.exists(p):
                return p
    else:
        cmds = [
            "google-chrome",
            "google-chrome-stable",
            "chromium",
            "chromium-browser",
            "microsoft-edge-stable",
            "microsoft-edge",
            "brave-browser",
        ]
        for cmd in cmds:
            path = shutil.which(cmd)
            if path:
                return path
    return None


@dataclass
class BrowserLaunchHandle:
    process: subprocess.Popen
    profile_dir: str | None = None


_active_browser_handle: BrowserLaunchHandle | None = None
_active_browser_lock = Lock()


def _seed_app_profile(profile_dir: str) -> None:
    """Seed browser preferences for the isolated launcher-only profile."""
    profile = Path(profile_dir) / "Default"
    profile.mkdir(parents=True, exist_ok=True)
    preferences_path = profile / "Preferences"
    preferences: dict[str, object] = {}
    if preferences_path.exists():
        try:
            loaded = json.loads(preferences_path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                preferences = loaded
        except (OSError, json.JSONDecodeError):
            preferences = {}

    translate = preferences.get("translate")
    if not isinstance(translate, dict):
        translate = {}
        preferences["translate"] = translate
    translate["enabled"] = False

    intl = preferences.get("intl")
    if not isinstance(intl, dict):
        intl = {}
        preferences["intl"] = intl
    intl["accept_languages"] = "de,en-US,en"

    preferences_path.write_text(
        json.dumps(preferences, ensure_ascii=False), encoding="utf-8"
    )


def open_browser_app_mode(url: str) -> BrowserLaunchHandle | None:
    global _active_browser_handle
    executable = find_browser_executable()
    if executable:
        profile_dir: str | None = None
        try:
            launch_args = [
                executable,
                f"--app={url}",
                "--start-maximized",
                "--new-window",
                # Dedicated temporary profiles would normally trigger first-run
                # onboarding every launch; suppress that for launcher UX.
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-search-engine-choice-screen",
                "--lang=de",
            ]
            profile_dir = tempfile.mkdtemp(prefix="llng-ui-")
            _seed_app_profile(profile_dir)
            # Use a dedicated profile to avoid handing off to an existing browser
            # process; that keeps a stable process handle for close monitoring.
            launch_args.append(f"--user-data-dir={profile_dir}")
            if sys.platform == "win32":
                process = subprocess.Popen(launch_args)
            else:
                process = subprocess.Popen(launch_args, start_new_session=True)
            handle = BrowserLaunchHandle(process=process, profile_dir=profile_dir)
            with _active_browser_lock:
                _active_browser_handle = handle
            return handle
        except OSError:
            if profile_dir:
                shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            if profile_dir:
                shutil.rmtree(profile_dir, ignore_errors=True)
    # Fallback if no supported browser is found or if launch fails
    webbrowser.open(url)
    return None


def close_browser_app_mode(timeout_seconds: float = 2.0) -> bool:
    global _active_browser_handle
    with _active_browser_lock:
        handle = _active_browser_handle
        # Clear the active handle eagerly so repeated shutdown requests do not
        # keep trying to terminate the same process twice.
        _active_browser_handle = None
    if handle is None:
        return False
    process = handle.process
    if process.poll() is None:
        try:
            process.terminate()
        except Exception:
            pass
        deadline = time.monotonic() + max(0.0, float(timeout_seconds))
        while time.monotonic() < deadline:
            if process.poll() is not None:
                break
            time.sleep(0.05)
        if process.poll() is None:
            try:
                process.kill()
            except Exception:
                pass
    if handle.profile_dir:
        shutil.rmtree(handle.profile_dir, ignore_errors=True)
    return True


def _monitor_browser_close(
    handle: BrowserLaunchHandle,
    on_closed: Callable[[], None],
    min_runtime_seconds: float = 1.5,
) -> None:
    def _watch() -> None:
        global _active_browser_handle
        started = time.monotonic()
        try:
            handle.process.wait()
            runtime = time.monotonic() - started
            if runtime >= min_runtime_seconds:
                on_closed()
        finally:
            with _active_browser_lock:
                if _active_browser_handle is handle:
                    _active_browser_handle = None
            if handle.profile_dir:
                shutil.rmtree(handle.profile_dir, ignore_errors=True)

    Thread(target=_watch, daemon=True).start()


def launch_ui_async(
    url: str, delay: float = 0.5, on_closed: Callable[[], None] | None = None
) -> None:
    def _launch() -> None:
        time.sleep(delay)
        handle = open_browser_app_mode(url)
        if handle is not None and on_closed is not None:
            _monitor_browser_close(handle, on_closed)

    Thread(target=_launch, daemon=True).start()
