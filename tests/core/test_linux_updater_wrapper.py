"""Regression tests for Linux updater wrapper edge cases."""

from __future__ import annotations

import hashlib
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


class LinuxUpdaterWrapperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.script_path = (
            Path.cwd() / "scripts" / "wrappers" / "linux" / "llng-updater.sh"
        )

    def test_wrapper_shebang_has_no_utf8_bom(self) -> None:
        raw = self.script_path.read_bytes()
        self.assertFalse(raw.startswith(b"\xef\xbb\xbf"))
        self.assertTrue(raw.startswith(b"#!"))

    def test_wrapper_uses_metadata_preserving_copy_for_preserve_paths(self) -> None:
        script = self.script_path.read_text(encoding="utf-8")
        self.assertIn('cp -a "$FROM_PATH" "$TO_PATH"', script)

    def test_wrapper_passes_owner_ids_to_elevated_child(self) -> None:
        script = self.script_path.read_text(encoding="utf-8")
        self.assertIn("LLNG_UPDATER_OWNER_UID", script)
        self.assertIn("LLNG_UPDATER_OWNER_GID", script)

    def test_wrapper_restores_write_access_to_resilio_config_directory(self) -> None:
        script = self.script_path.read_text(encoding="utf-8")
        self.assertIn(
            'restore_user_owner_if_known "${RESOLVED_TARGET_PATH}/config/resilio"',
            script,
        )

    def test_wrapper_strips_nested_update_state_from_preserved_data(self) -> None:
        script = self.script_path.read_text(encoding="utf-8")
        self.assertIn('rm -rf "${BACKUP_ROOT_PATH}/data/update"', script)
        self.assertIn('rm -rf "${TO_PATH}/update"', script)
        self.assertNotIn("refresh_default_extra_sync_items_config", script)
        self.assertNotIn("restore_default_extra_sync_items_config", script)

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_config_defaults_come_from_payload_without_config_preserve(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app"
            payload_dir = root / "payload-content" / "lanlauncherng-new"
            payload_tar = root / "payload.tar"
            manifest = root / "update-manifest.json"

            (target / "config").mkdir(parents=True, exist_ok=True)
            (target / "config" / "bootstrap.json").write_text(
                "old-defaults",
                encoding="utf-8",
            )
            (target / "config" / "keep.json").write_text(
                "keep-me",
                encoding="utf-8",
            )
            (target / "data").mkdir(parents=True, exist_ok=True)
            (target / "old.txt").write_text("old-build", encoding="utf-8")

            (payload_dir / "config").mkdir(parents=True, exist_ok=True)
            (payload_dir / "config" / "bootstrap.json").write_text(
                "new-defaults",
                encoding="utf-8",
            )
            (payload_dir / "health.txt").write_text("ok", encoding="utf-8")

            with tarfile.open(payload_tar, "w") as archive:
                archive.add(payload_dir, arcname="lanlauncherng-new")

            checksum = hashlib.sha256(payload_tar.read_bytes()).hexdigest()
            manifest.write_text("{}", encoding="utf-8")

            command = [
                "sh",
                str(self.script_path),
                "--manifest-path",
                str(manifest),
                "--current-version",
                "0.1.7",
                "--target-version",
                "0.1.8",
                "--session-id",
                "sess-default-config",
                "--payload-path",
                str(payload_tar),
                "--payload-sha256",
                checksum,
                "--install-mode",
                "directory_swap",
                "--install-target-path",
                str(target),
                "--preserve-paths-csv",
                "data",
                "--health-check-type",
                "file_exists",
                "--health-check-path",
                "health.txt",
                "--repo-root",
                str(target),
            ]
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.fail(
                    "Updater wrapper failed unexpectedly:\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            self.assertEqual(
                (target / "config" / "bootstrap.json").read_text(
                    encoding="utf-8"
                ),
                "new-defaults",
            )
            self.assertFalse((target / "config" / "keep.json").exists())

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_directory_swap_restores_launcher_write_access_to_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app"
            payload_dir = root / "payload-content" / "lanlauncherng-new"
            config_dir = payload_dir / "config" / "resilio"
            payload_tar = root / "payload.tar"
            manifest = root / "update-manifest.json"

            (target / "data").mkdir(parents=True)
            config_dir.mkdir(parents=True)
            config_file = config_dir / "config.json"
            config_file.write_text('{"storage_path":"data/sync"}\n', encoding="utf-8")
            config_file.chmod(0o444)
            config_dir.chmod(0o555)
            (payload_dir / "health.txt").write_text("ok", encoding="utf-8")

            with tarfile.open(payload_tar, "w") as archive:
                archive.add(payload_dir, arcname="lanlauncherng-new")

            checksum = hashlib.sha256(payload_tar.read_bytes()).hexdigest()
            manifest.write_text("{}", encoding="utf-8")
            command = [
                "sh",
                str(self.script_path),
                "--manifest-path",
                str(manifest),
                "--current-version",
                "0.1.7",
                "--target-version",
                "0.1.8",
                "--session-id",
                "sess-config-owner",
                "--payload-path",
                str(payload_tar),
                "--payload-sha256",
                checksum,
                "--install-mode",
                "directory_swap",
                "--install-target-path",
                str(target),
                "--preserve-paths-csv",
                "data",
                "--health-check-type",
                "file_exists",
                "--health-check-path",
                "health.txt",
                "--repo-root",
                str(target),
            ]
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                env={
                    **os.environ,
                    "LLNG_UPDATER_OWNER_UID": str(os.getuid()),
                    "LLNG_UPDATER_OWNER_GID": str(os.getgid()),
                },
            )
            if result.returncode != 0:
                self.fail(
                    "Updater wrapper failed unexpectedly:\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            installed_config = target / "config" / "resilio" / "config.json"
            installed_config_dir = installed_config.parent
            self.assertTrue(installed_config.stat().st_mode & 0o200)
            self.assertTrue(installed_config_dir.stat().st_mode & 0o200)
            self.assertEqual(installed_config.stat().st_uid, os.getuid())
            self.assertEqual(installed_config_dir.stat().st_uid, os.getuid())
            probe = installed_config_dir / ".atomic-write-probe"
            probe.write_text("ok", encoding="utf-8")
            self.assertEqual(probe.read_text(encoding="utf-8"), "ok")

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_directory_swap_succeeds_when_target_matches_repo_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app"
            payload_dir = root / "payload-content" / "lanlauncherng-new"
            payload_tar = root / "payload.tar"
            manifest = root / "update-manifest.json"

            (target / "data").mkdir(parents=True, exist_ok=True)
            (target / "config").mkdir(parents=True, exist_ok=True)
            (target / "data" / "persist.txt").write_text("keep-me", encoding="utf-8")
            (target / "old.txt").write_text("old-build", encoding="utf-8")

            payload_dir.mkdir(parents=True, exist_ok=True)
            (payload_dir / "new.txt").write_text("new-build", encoding="utf-8")
            (payload_dir / "health.txt").write_text("ok", encoding="utf-8")

            with tarfile.open(payload_tar, "w") as archive:
                archive.add(payload_dir, arcname="lanlauncherng-new")

            checksum = hashlib.sha256(payload_tar.read_bytes()).hexdigest()
            manifest.write_text("{}", encoding="utf-8")

            command = [
                "sh",
                str(self.script_path),
                "--manifest-path",
                str(manifest),
                "--current-version",
                "0.1.7",
                "--target-version",
                "0.1.8",
                "--session-id",
                "sess-self-move",
                "--payload-path",
                str(payload_tar),
                "--payload-sha256",
                checksum,
                "--install-mode",
                "directory_swap",
                "--install-target-path",
                str(target),
                "--preserve-paths-csv",
                "data",
                "--health-check-type",
                "file_exists",
                "--health-check-path",
                "health.txt",
                "--repo-root",
                str(target),
            ]
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.fail(
                    "Updater wrapper failed unexpectedly:\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            self.assertTrue((target / "new.txt").is_file())
            self.assertTrue((target / "health.txt").is_file())
            self.assertEqual(
                (target / "data" / "persist.txt").read_text(encoding="utf-8"),
                "keep-me",
            )
            backup_current = (
                target / "data" / "update" / "backup" / "sess-self-move" / "current"
            )
            self.assertTrue(backup_current.is_dir())
            self.assertTrue((backup_current / "old.txt").is_file())

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_directory_swap_removes_old_update_history_from_backup_and_preserved_data(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app"
            payload_dir = root / "payload-content" / "lanlauncherng-new"
            payload_tar = root / "payload.tar"
            manifest = root / "update-manifest.json"

            (target / "data" / "user-cache").mkdir(parents=True, exist_ok=True)
            (target / "config").mkdir(parents=True, exist_ok=True)
            (target / "data" / "user-cache" / "persist.txt").write_text(
                "keep-me", encoding="utf-8"
            )
            stale_backup = (
                target / "data" / "update" / "backup" / "old-session" / "current"
            )
            stale_backup.mkdir(parents=True, exist_ok=True)
            (stale_backup / "nested.txt").write_text("stale", encoding="utf-8")
            (target / "data" / "update" / "session-old-session.json").write_text(
                "{}", encoding="utf-8"
            )
            (target / "old.txt").write_text("old-build", encoding="utf-8")

            payload_dir.mkdir(parents=True, exist_ok=True)
            (payload_dir / "new.txt").write_text("new-build", encoding="utf-8")
            (payload_dir / "health.txt").write_text("ok", encoding="utf-8")

            with tarfile.open(payload_tar, "w") as archive:
                archive.add(payload_dir, arcname="lanlauncherng-new")

            checksum = hashlib.sha256(payload_tar.read_bytes()).hexdigest()
            manifest.write_text("{}", encoding="utf-8")

            command = [
                "sh",
                str(self.script_path),
                "--manifest-path",
                str(manifest),
                "--current-version",
                "0.1.7",
                "--target-version",
                "0.1.8",
                "--session-id",
                "sess-pruned-backup",
                "--payload-path",
                str(payload_tar),
                "--payload-sha256",
                checksum,
                "--install-mode",
                "directory_swap",
                "--install-target-path",
                str(target),
                "--preserve-paths-csv",
                "data",
                "--health-check-type",
                "file_exists",
                "--health-check-path",
                "health.txt",
                "--repo-root",
                str(target),
            ]
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.fail(
                    "Updater wrapper failed unexpectedly:\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            backup_root = target / "data" / "update" / "backup"
            self.assertEqual(
                sorted(entry.name for entry in backup_root.iterdir() if entry.is_dir()),
                ["sess-pruned-backup"],
            )

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_directory_swap_preserves_local_resilio_binaries_when_payload_lacks_them(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app"
            payload_dir = root / "payload-content" / "lanlauncherng-new"
            payload_tar = root / "payload.tar"
            manifest = root / "update-manifest.json"

            (target / "vendor" / "bin" / "linux-x64").mkdir(parents=True, exist_ok=True)
            (target / "vendor" / "licenses" / "resilio").mkdir(
                parents=True, exist_ok=True
            )
            (target / "vendor" / "bin" / "linux-x64" / "rslsync").write_text(
                "old-rslsync", encoding="utf-8"
            )
            (target / "vendor" / "licenses" / "resilio" / "llng.btskey").write_text(
                "old-key", encoding="utf-8"
            )
            (target / "data").mkdir(parents=True, exist_ok=True)

            payload_dir.mkdir(parents=True, exist_ok=True)
            (payload_dir / "new.txt").write_text("new-build", encoding="utf-8")

            with tarfile.open(payload_tar, "w") as archive:
                archive.add(payload_dir, arcname="lanlauncherng-new")

            checksum = hashlib.sha256(payload_tar.read_bytes()).hexdigest()
            manifest.write_text("{}", encoding="utf-8")

            command = [
                "sh",
                str(self.script_path),
                "--manifest-path",
                str(manifest),
                "--current-version",
                "0.1.7",
                "--target-version",
                "0.1.8",
                "--session-id",
                "sess-preserve-resilio",
                "--payload-path",
                str(payload_tar),
                "--payload-sha256",
                checksum,
                "--install-mode",
                "directory_swap",
                "--install-target-path",
                str(target),
                "--preserve-paths-csv",
                "data,vendor/bin/linux-x64/rslsync,vendor/licenses/resilio/llng.btskey",
                "--health-check-type",
                "file_exists",
                "--health-check-path",
                "new.txt",
                "--repo-root",
                str(target),
            ]
            result = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.fail(
                    "Updater wrapper failed unexpectedly:\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            self.assertEqual(
                (target / "vendor" / "bin" / "linux-x64" / "rslsync").read_text(
                    encoding="utf-8"
                ),
                "old-rslsync",
            )
            self.assertEqual(
                (target / "vendor" / "licenses" / "resilio" / "llng.btskey").read_text(
                    encoding="utf-8"
                ),
                "old-key",
            )

    @unittest.skipUnless(os.name == "posix", "Linux wrapper test requires POSIX shell")
    def test_directory_swap_restores_or_generates_run_sh_when_payload_misses_it(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app"
            payload_dir = root / "payload-content" / "lanlauncherng-new"
            payload_tar = root / "payload.tar"
            manifest = root / "update-manifest.json"

            (target / "data").mkdir(parents=True, exist_ok=True)
            (target / "config").mkdir(parents=True, exist_ok=True)
            (target / "run.sh").write_text(
                "#!/usr/bin/env bash\necho old\n", encoding="utf-8"
            )

            payload_dir.mkdir(parents=True, exist_ok=True)
            (payload_dir / "run.bat").write_text("@echo off\r\n", encoding="utf-8")
            (payload_dir / "health.txt").write_text("ok", encoding="utf-8")

            with tarfile.open(payload_tar, "w") as archive:
                archive.add(payload_dir, arcname="lanlauncherng-new")

            checksum = hashlib.sha256(payload_tar.read_bytes()).hexdigest()
            manifest.write_text("{}", encoding="utf-8")

            command = [
                "sh",
                str(self.script_path),
                "--manifest-path",
                str(manifest),
                "--current-version",
                "0.1.7",
                "--target-version",
                "0.1.8",
                "--session-id",
                "sess-missing-runsh",
                "--payload-path",
                str(payload_tar),
                "--payload-sha256",
                checksum,
                "--install-mode",
                "directory_swap",
                "--install-target-path",
                str(target),
                "--preserve-paths-csv",
                "data",
                "--health-check-type",
                "file_exists",
                "--health-check-path",
                "health.txt",
                "--repo-root",
                str(target),
            ]
            result = subprocess.run(  # noqa: S603
                command,
                check=False,
                capture_output=True,
                text=True,
            )
            if result.returncode != 0:
                self.fail(
                    "Updater wrapper failed unexpectedly:\n"
                    f"stdout:\n{result.stdout}\n"
                    f"stderr:\n{result.stderr}"
                )

            self.assertTrue((target / "run.sh").is_file())
            self.assertTrue((target / "run.bat").is_file())


if __name__ == "__main__":
    unittest.main()
