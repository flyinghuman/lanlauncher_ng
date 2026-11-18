"""Regression tests for Linux CMD runtime wrapper behavior."""

from __future__ import annotations

import os
import subprocess
import tempfile
import unittest
from pathlib import Path


class LinuxRunCmdWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script_path = (
            Path.cwd() / "scripts" / "wrappers" / "linux" / "run-cmd-wrapper.sh"
        )

    def test_wrapper_shebang_has_no_utf8_bom(self) -> None:
        raw = self.script_path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(raw.startswith(b"#!"))

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_runtime_failure_returns_nonzero_and_emits_failure_line(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmd_script = Path(tmp) / "game_start.cmd"
            cmd_script.write_text("@echo off\r\n", encoding="utf-8")
            command = [
                "bash",
                str(self.script_path),
                "--runtime",
                "wine",
                "--runtime-binary",
                "/bin/false",
                str(cmd_script),
            ]
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("runtime launch failed", result.stderr)

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_non_tty_run_does_not_start_countdown_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmd_script = Path(tmp) / "game_start.cmd"
            cmd_script.write_text("@echo off\r\n", encoding="utf-8")
            command = [
                "bash",
                str(self.script_path),
                "--runtime",
                "wine",
                "--runtime-binary",
                "/bin/false",
                str(cmd_script),
            ]
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn("closing this terminal in", result.stdout)

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_hold_open_flag_in_non_tty_mode_does_not_block(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cmd_script = Path(tmp) / "game_start.cmd"
            cmd_script.write_text("@echo off\r\n", encoding="utf-8")
            command = [
                "bash",
                str(self.script_path),
                "--runtime",
                "wine",
                "--runtime-binary",
                "/bin/true",
                "--hold-open",
                str(cmd_script),
            ]
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertNotIn("closing this terminal in", result.stdout)

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_proton_launch_sets_steam_client_install_path_for_ge_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_binary = (
                root
                / ".steam"
                / "root"
                / "compatibilitytools.d"
                / "GE-Proton10-32"
                / "proton"
            )
            runtime_binary.parent.mkdir(parents=True, exist_ok=True)
            runtime_binary.write_text(
                "#!/usr/bin/env bash\n"
                'echo "STEAM_COMPAT_CLIENT_INSTALL_PATH=${STEAM_COMPAT_CLIENT_INSTALL_PATH:-}"\n',
                encoding="utf-8",
            )
            runtime_binary.chmod(0o755)

            cmd_script = root / "game_start.cmd"
            cmd_script.write_text("@echo off\r\n", encoding="utf-8")
            command = [
                "bash",
                str(self.script_path),
                "--runtime",
                "proton-ge",
                "--runtime-binary",
                str(runtime_binary),
                str(cmd_script),
            ]
            env = os.environ.copy()
            env["HOME"] = str(root)
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn(
                f"STEAM_COMPAT_CLIENT_INSTALL_PATH={root / '.steam' / 'root'}",
                result.stdout,
            )

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_proton_launch_sets_steam_client_install_path_for_valve_layout(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_binary = (
                root
                / ".local"
                / "share"
                / "Steam"
                / "steamapps"
                / "common"
                / "Proton 9.0"
                / "proton"
            )
            runtime_binary.parent.mkdir(parents=True, exist_ok=True)
            runtime_binary.write_text(
                "#!/usr/bin/env bash\n"
                'echo "STEAM_COMPAT_CLIENT_INSTALL_PATH=${STEAM_COMPAT_CLIENT_INSTALL_PATH:-}"\n',
                encoding="utf-8",
            )
            runtime_binary.chmod(0o755)

            cmd_script = root / "game_start.cmd"
            cmd_script.write_text("@echo off\r\n", encoding="utf-8")
            command = [
                "bash",
                str(self.script_path),
                "--runtime",
                "proton",
                "--runtime-binary",
                str(runtime_binary),
                str(cmd_script),
            ]
            env = os.environ.copy()
            env["HOME"] = str(root)
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
                env=env,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn(
                f"STEAM_COMPAT_CLIENT_INSTALL_PATH={root / '.local' / 'share' / 'Steam'}",
                result.stdout,
            )

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_wine_launch_sets_game_specific_wineprefix_when_compat_path_is_given(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            runtime_binary = root / "wine-stub.sh"
            runtime_binary.write_text(
                '#!/usr/bin/env bash\necho "WINEPREFIX=${WINEPREFIX:-}"\n',
                encoding="utf-8",
            )
            runtime_binary.chmod(0o755)
            compat_path = root / "LAN" / "demo" / ".compatdata" / "wine"
            cmd_script = root / "game_start.cmd"
            cmd_script.write_text("@echo off\r\n", encoding="utf-8")
            command = [
                "bash",
                str(self.script_path),
                "--runtime",
                "wine",
                "--runtime-binary",
                str(runtime_binary),
                "--compat-data-path",
                str(compat_path),
                str(cmd_script),
            ]
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 0)
            self.assertIn(f"WINEPREFIX={compat_path}", result.stdout)


if __name__ == "__main__":
    unittest.main()
