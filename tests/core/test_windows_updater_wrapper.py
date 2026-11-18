"""Regression tests for Windows updater wrapper edge cases."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


class WindowsUpdaterWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script_path = (
            Path.cwd() / "scripts" / "wrappers" / "windows" / "llng-updater.ps1"
        )

    def test_wrapper_uses_parent_exit_handoff(self) -> None:
        script = self.script_path.read_text(encoding="utf-8")
        self.assertIn("ParentProcessId", script)
        self.assertIn("Wait-ForParentExit", script)

    def test_wrapper_strips_nested_update_state_from_preserved_data(self) -> None:
        script = self.script_path.read_text(encoding="utf-8")
        self.assertIn("Remove-StaleUpdaterStateFromBackup", script)
        self.assertIn('Join-Path $backupCurrentPath "data\\update"', script)
        self.assertIn('Join-Path $toPath "update"', script)
        self.assertNotIn("Refresh-DefaultExtraSyncItemsConfig", script)
        self.assertNotIn("Restore-DefaultExtraSyncItemsConfig", script)

    @unittest.skipUnless(os.name == "nt", "Windows wrapper test requires Windows")
    @unittest.skipIf(
        os.environ.get("LLNG_TEST_WINE") == "1",
        "Wine does not provide the Windows PowerShell host used by this integration test",
    )
    def test_directory_swap_waits_for_parent_and_promotes_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app"
            payload_dir = root / "payload-content" / "lanlauncherng-new"
            payload_zip = root / "payload.zip"
            manifest = root / "update-manifest.json"
            external_wrapper = root / "runtime-helper" / "llng-updater.ps1"
            external_wrapper.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.script_path, external_wrapper)

            (target / "data").mkdir(parents=True, exist_ok=True)
            (target / "config").mkdir(parents=True, exist_ok=True)
            (target / "data" / "persist.txt").write_text("keep-me", encoding="utf-8")
            (target / "old.txt").write_text("old-build", encoding="utf-8")
            hold_script = target / "hold.ps1"
            hold_script.write_text("Start-Sleep -Seconds 2\n", encoding="utf-8")

            payload_dir.mkdir(parents=True, exist_ok=True)
            (payload_dir / "new.txt").write_text("new-build", encoding="utf-8")
            (payload_dir / "health.txt").write_text("ok", encoding="utf-8")

            with zipfile.ZipFile(
                payload_zip, "w", compression=zipfile.ZIP_DEFLATED
            ) as archive:
                for path in payload_dir.rglob("*"):
                    if path.is_file():
                        archive.write(path, path.relative_to(payload_dir.parent))

            checksum = hashlib.sha256(payload_zip.read_bytes()).hexdigest()
            manifest.write_text("{}", encoding="utf-8")

            hold_proc = subprocess.Popen(  # noqa: S603
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(hold_script),
                ],
                cwd=str(target),
            )
            try:
                command = [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    str(external_wrapper),
                    "-ManifestPath",
                    str(manifest),
                    "-CurrentVersion",
                    "0.4.3",
                    "-TargetVersion",
                    "0.4.4",
                    "-SessionId",
                    "sess-self-hosted",
                    "-PayloadPath",
                    str(payload_zip),
                    "-PayloadSha256",
                    checksum,
                    "-InstallMode",
                    "directory_swap",
                    "-InstallTargetPath",
                    str(target),
                    "-PreservePathsCsv",
                    "data",
                    "-HealthCheckType",
                    "file_exists",
                    "-HealthCheckPath",
                    "health.txt",
                    "-RepoRoot",
                    str(target),
                    "-ParentProcessId",
                    str(hold_proc.pid),
                ]
                result = subprocess.run(  # noqa: S603
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
            finally:
                hold_proc.wait(timeout=10)

            if result.returncode != 0:
                self.fail(
                    "Windows updater wrapper failed unexpectedly:\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            self.assertIn("waiting for parent process", result.stdout)
            self.assertIn("update completed successfully", result.stdout)
            self.assertIn("this window will close in 10 seconds", result.stdout)
            self.assertTrue((target / "new.txt").is_file())
            self.assertTrue((target / "health.txt").is_file())
            self.assertEqual(
                (target / "data" / "persist.txt").read_text(encoding="utf-8"),
                "keep-me",
            )

            journal_path = target / "data" / "update" / "session-sess-self-hosted.json"
            self.assertTrue(journal_path.is_file())
            journal = json.loads(journal_path.read_text(encoding="utf-8-sig"))
            self.assertEqual(journal["phase"], "apply")
            self.assertEqual(journal["status"], "ok")

            backup_current = (
                target / "data" / "update" / "backup" / "sess-self-hosted" / "current"
            )
            self.assertTrue(backup_current.is_dir())
            self.assertTrue((backup_current / "old.txt").is_file())


if __name__ == "__main__":
    unittest.main()
