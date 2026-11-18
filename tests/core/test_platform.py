"""Tests for platform adapters and factory selection."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.platform.factory import create_platform_adapter
from src.core.platform.linux.adapter import LinuxPlatformAdapter
from src.core.platform.windows.adapter import WindowsPlatformAdapter


class PlatformAdapterTests(unittest.TestCase):
    def test_factory_selects_windows(self) -> None:
        adapter = create_platform_adapter(force_platform="Windows")
        self.assertIsInstance(adapter, WindowsPlatformAdapter)

    def test_factory_selects_linux(self) -> None:
        adapter = create_platform_adapter(force_platform="Linux")
        self.assertIsInstance(adapter, LinuxPlatformAdapter)

    def test_validate_storage_path_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = WindowsPlatformAdapter()
            result = adapter.validate_storage_path(tmp)
            self.assertTrue(result.ok)
            self.assertTrue(result.writable)

    def test_validate_storage_path_linux(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = LinuxPlatformAdapter()
            result = adapter.validate_storage_path(tmp)
            self.assertTrue(result.ok)
            self.assertTrue(result.writable)

    def test_validate_storage_path_linux_windows_fs_warning(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = LinuxPlatformAdapter()
            with (
                patch(
                    "src.core.platform.linux.adapter.shutil.which",
                    return_value="/usr/bin/stat",
                ),
                patch("src.core.platform.linux.adapter.subprocess.run") as mocked_run,
            ):
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = "fuseblk\n"
                mocked_run.return_value.stderr = ""
                result = adapter.validate_storage_path(tmp)
            self.assertTrue(result.ok)
            self.assertEqual(result.message, "ok_windows_filesystem_warning")

    def test_open_folder_missing_path(self) -> None:
        adapter = WindowsPlatformAdapter()
        result = adapter.open_folder("Z:/path/does/not/exist")
        self.assertFalse(result.ok)

    def test_linux_open_folder_without_xdg_open(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adapter = LinuxPlatformAdapter()
            with patch(
                "src.core.platform.linux.adapter.shutil.which", return_value=None
            ):
                result = adapter.open_folder(tmp)
            self.assertFalse(result.ok)
            self.assertEqual(result.message, "xdg_open_not_found")

    def test_linux_open_folder_allows_existing_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "docs.html"
            file_path.write_text("<html></html>", encoding="utf-8")
            adapter = LinuxPlatformAdapter()
            with (
                patch(
                    "src.core.platform.linux.adapter.shutil.which",
                    return_value="/usr/bin/xdg-open",
                ),
                patch(
                    "src.core.platform.linux.adapter.subprocess.Popen"
                ) as mocked_popen,
            ):
                result = adapter.open_folder(str(file_path))
            self.assertTrue(result.ok)
            args, _kwargs = mocked_popen.call_args
            self.assertEqual(args[0][0], "/usr/bin/xdg-open")
            self.assertEqual(
                Path(args[0][1]).resolve(strict=False),
                file_path.resolve(strict=False),
            )

    @unittest.skipUnless(hasattr(__import__("os"), "startfile"), "requires Windows")
    def test_windows_open_folder_allows_existing_file_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            file_path = Path(tmp) / "docs.html"
            file_path.write_text("<html></html>", encoding="utf-8")
            adapter = WindowsPlatformAdapter()
            with patch("src.core.platform.windows.adapter.os.startfile") as mocked_open:
                result = adapter.open_folder(str(file_path))
            self.assertTrue(result.ok)
            called_path = mocked_open.call_args.args[0]
            self.assertEqual(
                Path(called_path).resolve(strict=False),
                file_path.resolve(strict=False),
            )

    def test_normalize_path(self) -> None:
        adapter = WindowsPlatformAdapter()
        normalized = adapter.normalize_path(".")
        self.assertTrue(Path(normalized).is_absolute())

    @unittest.skipUnless(
        hasattr(__import__("ctypes"), "WinDLL"),
        "requires ctypes.WinDLL (Windows runtime)",
    )
    def test_windows_storage_locations_include_drive_labels(self) -> None:
        adapter = WindowsPlatformAdapter()

        class FakeKernel32:
            def GetLogicalDrives(self) -> int:
                return (1 << 2) | (1 << 3)

            def GetVolumeInformationW(
                self, root: str, volume_name: object, *_args: object
            ) -> int:
                if root == "C:\\":
                    volume_name.value = "System"
                    return 1
                if root == "D:\\":
                    volume_name.value = "LAN"
                    return 1
                return 0

        with patch(
            "src.core.platform.windows.adapter.ctypes.WinDLL",
            return_value=FakeKernel32(),
        ):
            locations = adapter.list_storage_locations()

        self.assertEqual(len(locations), 2)
        self.assertEqual(locations[0]["id"], "C")
        self.assertEqual(locations[0]["display"], "C: (System)")
        self.assertEqual(locations[1]["id"], "D")
        self.assertEqual(locations[1]["display"], "D: (LAN)")

    def test_linux_storage_locations_are_empty(self) -> None:
        adapter = LinuxPlatformAdapter()
        self.assertEqual(adapter.list_storage_locations(), [])

    def test_windows_launch_cmd_uses_interactive_console(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "game_start.cmd"
            script.write_text("@echo off", encoding="utf-8")
            adapter = WindowsPlatformAdapter()
            with patch(
                "src.core.platform.windows.adapter.subprocess.Popen"
            ) as mocked_popen:
                result = adapter.launch_executable(str(script), args=["arg1"])
            self.assertTrue(result.ok)
            args, kwargs = mocked_popen.call_args
            self.assertEqual(args[0][:3], ["cmd.exe", "/c", str(script)])
            self.assertEqual(args[0][3], "arg1")
            self.assertIn("creationflags", kwargs)

    def test_linux_launch_uses_interactive_terminal_when_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "game_start.sh"
            script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            adapter = LinuxPlatformAdapter()
            with (
                patch(
                    "src.core.platform.linux.adapter.shutil.which",
                    side_effect=lambda name: {
                        "x-terminal-emulator": "/usr/bin/x-terminal-emulator",
                        "bash": "/usr/bin/bash",
                    }.get(name),
                ),
                patch(
                    "src.core.platform.linux.adapter.subprocess.Popen"
                ) as mocked_popen,
            ):
                result = adapter.launch_executable(str(script), args=["arg1"])
            self.assertTrue(result.ok)
            args, _kwargs = mocked_popen.call_args
            command = args[0]
            self.assertEqual(command[0], "/usr/bin/x-terminal-emulator")
            self.assertIn(str(script), command)
            self.assertIn("arg1", command)

    def test_linux_launch_falls_back_when_no_terminal_available(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "game_start.sh"
            script.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
            adapter = LinuxPlatformAdapter()
            with (
                patch(
                    "src.core.platform.linux.adapter.shutil.which", return_value=None
                ),
                patch(
                    "src.core.platform.linux.adapter.subprocess.Popen"
                ) as mocked_popen,
            ):
                result = adapter.launch_executable(str(script), args=["arg1"])
            self.assertTrue(result.ok)
            args, _kwargs = mocked_popen.call_args
            self.assertEqual(args[0], [str(script), "arg1"])

    def test_linux_install_common_wine_dependencies_starts_winetricks(self) -> None:
        adapter = LinuxPlatformAdapter()
        with (
            patch(
                "src.core.platform.linux.adapter.shutil.which",
                side_effect=lambda name: {
                    "winetricks": "/usr/bin/winetricks",
                    "wine": "/usr/bin/wine",
                    "x-terminal-emulator": "/usr/bin/x-terminal-emulator",
                    "bash": "/usr/bin/bash",
                }.get(name),
            ),
            patch("src.core.platform.linux.adapter.subprocess.Popen") as mocked_popen,
        ):
            result = adapter.install_common_wine_dependencies(["d3dx9", "vcrun2008"])
        self.assertTrue(result.ok)
        self.assertEqual(result.message, "wine_dependencies_install_started")
        args, kwargs = mocked_popen.call_args
        self.assertEqual(args[0][0], "/usr/bin/x-terminal-emulator")
        self.assertIn("WINEPREFIX", kwargs["env"])
        self.assertEqual(kwargs["env"]["WINEPREFIX"], str(Path.home() / ".wine"))

    def test_linux_install_common_wine_dependencies_prefers_explicit_bundle_path(
        self,
    ) -> None:
        adapter = LinuxPlatformAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            bundled = Path(tmp) / "winetricks"
            bundled.write_text("#!/bin/sh\n", encoding="utf-8")
            cache_dir = Path(tmp) / "cache"
            with (
                patch(
                    "src.core.platform.linux.adapter.shutil.which",
                    side_effect=lambda name: {
                        "winetricks": "/usr/bin/winetricks",
                        "wine": "/usr/bin/wine",
                    }.get(name),
                ),
                patch(
                    "src.core.platform.linux.adapter.subprocess.Popen"
                ) as mocked_popen,
            ):
                result = adapter.install_common_wine_dependencies_for_prefix(
                    "/srv/LAN/demo/.compatdata/proton",
                    ["d3dx9"],
                    winetricks_path=str(bundled),
                    cache_path=str(cache_dir),
                )
        self.assertTrue(result.ok)
        args, kwargs = mocked_popen.call_args
        self.assertEqual(args[0][0], str(bundled))
        self.assertEqual(kwargs["env"]["WINETRICKS_CACHE"], str(cache_dir))
        self.assertEqual(kwargs["env"]["W_CACHE"], str(cache_dir))

    def test_linux_install_common_wine_dependencies_for_prefix_sets_env(self) -> None:
        adapter = LinuxPlatformAdapter()
        with (
            patch(
                "src.core.platform.linux.adapter.shutil.which",
                side_effect=lambda name: {
                    "winetricks": "/usr/bin/winetricks",
                    "wine": "/usr/bin/wine",
                }.get(name),
            ),
            patch("src.core.platform.linux.adapter.subprocess.Popen") as mocked_popen,
        ):
            result = adapter.install_common_wine_dependencies_for_prefix(
                "/srv/LAN/demo/.compatdata/proton",
                ["d3dx9", "vcrun2008"],
            )
        self.assertTrue(result.ok)
        self.assertEqual(result.message, "wine_dependencies_install_started")
        args, kwargs = mocked_popen.call_args
        self.assertEqual(args[0][0], "/usr/bin/winetricks")
        self.assertEqual(
            kwargs["env"]["WINEPREFIX"], "/srv/LAN/demo/.compatdata/proton"
        )

    def test_linux_install_common_wine_dependencies_for_prefix_requires_prefix(
        self,
    ) -> None:
        adapter = LinuxPlatformAdapter()
        result = adapter.install_common_wine_dependencies_for_prefix("", ["d3dx9"])
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "invalid_wine_prefix")

    def test_linux_install_common_wine_dependencies_requires_winetricks(self) -> None:
        adapter = LinuxPlatformAdapter()
        with patch(
            "src.core.platform.linux.adapter.shutil.which",
            side_effect=lambda name: {
                "wine": "/usr/bin/wine",
            }.get(name),
        ):
            result = adapter.install_common_wine_dependencies(["d3dx9"])
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "winetricks_not_found")

    def test_linux_open_wine_prefix_uninstaller_sets_env(self) -> None:
        adapter = LinuxPlatformAdapter()
        with tempfile.TemporaryDirectory() as tmp:
            prefix = Path(tmp) / ".compatdata" / "wine"
            prefix.mkdir(parents=True, exist_ok=True)
            with (
                patch(
                    "src.core.platform.linux.adapter.shutil.which",
                    side_effect=lambda name: {
                        "wine": "/usr/bin/wine",
                        "x-terminal-emulator": "/usr/bin/x-terminal-emulator",
                        "bash": "/usr/bin/bash",
                    }.get(name),
                ),
                patch(
                    "src.core.platform.linux.adapter.subprocess.Popen"
                ) as mocked_popen,
            ):
                result = adapter.open_wine_prefix_uninstaller(str(prefix))
        self.assertTrue(result.ok)
        args, kwargs = mocked_popen.call_args
        self.assertEqual(args[0][0], "/usr/bin/x-terminal-emulator")
        self.assertEqual(kwargs["env"]["WINEPREFIX"], str(prefix))

    def test_windows_configure_sync_network_mode_invokes_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "resilio-network-mode.ps1"
            binary = Path(tmp) / "btsync.exe"
            script.write_text("Write-Output ok", encoding="utf-8")
            binary.write_text("stub", encoding="utf-8")

            adapter = WindowsPlatformAdapter()
            with patch(
                "src.core.platform.windows.adapter.subprocess.run"
            ) as mocked_run:
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = "ok"
                mocked_run.return_value.stderr = ""
                result = adapter.configure_sync_network_mode(
                    script_path=str(script),
                    sync_binary_path=str(binary),
                    mode="lan",
                )
            self.assertTrue(result.ok)
            self.assertEqual(result.message, "network_mode_applied")
            args, _kwargs = mocked_run.call_args
            self.assertIn(str(script), args[0])
            self.assertIn("lan", args[0])

    def test_linux_configure_sync_network_mode_requires_sudo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "resilio-network-mode.sh"
            script.write_text("echo ok", encoding="utf-8")
            adapter = LinuxPlatformAdapter()
            with patch(
                "src.core.platform.linux.adapter.shutil.which", return_value=None
            ):
                result = adapter.configure_sync_network_mode(
                    script_path=str(script),
                    sync_binary_path="vendor/bin/linux-x64/rslsync",
                    mode="lan",
                )
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "sudo_not_found")

    def test_windows_set_local_network_private_invokes_script(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "set-lan-network-private.ps1"
            script.write_text("Write-Output ok", encoding="utf-8")
            adapter = WindowsPlatformAdapter()
            with patch(
                "src.core.platform.windows.adapter.subprocess.run"
            ) as mocked_run:
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = "ok"
                mocked_run.return_value.stderr = ""
                result = adapter.set_local_network_private(str(script))
            self.assertTrue(result.ok)
            self.assertEqual(result.message, "network_profile_applied")
            args, _kwargs = mocked_run.call_args
            self.assertIn(str(script), args[0])

    def test_linux_set_local_network_private_not_supported(self) -> None:
        adapter = LinuxPlatformAdapter()
        result = adapter.set_local_network_private(
            "scripts/wrappers/windows/set-lan-network-private.ps1"
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.message, "not_supported_on_platform")


if __name__ == "__main__":
    unittest.main()
