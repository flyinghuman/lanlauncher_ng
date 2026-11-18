"""Integration-style shutdown updater coverage for success/failure/recovery."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.config.loader import AppConfig
from src.core.service.app import Application


@unittest.skipUnless(
    os.name == "posix", "Updater wrapper integration requires POSIX shell"
)
class ShutdownUpdateIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.wrapper = Path.cwd() / "scripts" / "wrappers" / "linux" / "llng-updater.sh"

    def _create_payload_tar(self, root: Path, marker_text: str) -> tuple[Path, str]:
        payload_src = root / "payload-src" / "lanlauncherng"
        payload_src.mkdir(parents=True, exist_ok=True)
        (payload_src / "run.sh").write_text("#!/usr/bin/env sh\n", encoding="utf-8")
        (payload_src / "marker.txt").write_text(marker_text, encoding="utf-8")
        payload_tar = root / "payload.tar"
        with tarfile.open(payload_tar, "w") as archive:
            archive.add(payload_src, arcname="lanlauncherng")
        payload_sha = hashlib.sha256(payload_tar.read_bytes()).hexdigest()
        return payload_tar, payload_sha

    def _run_wrapper(
        self, root: Path, session_id: str, command_overrides: list[str]
    ) -> subprocess.CompletedProcess[str]:
        manifest = root / "update-manifest.json"
        manifest.write_text("{}", encoding="utf-8")
        payload_tar, payload_sha = self._create_payload_tar(
            root, f"marker-{session_id}"
        )
        cmd = [
            "sh",
            str(self.wrapper),
            "--manifest-path",
            str(manifest),
            "--current-version",
            "0.1.0",
            "--target-version",
            "0.2.0",
            "--session-id",
            session_id,
            "--payload-path",
            str(payload_tar),
            "--payload-sha256",
            payload_sha,
            "--install-mode",
            "noop",
            "--install-target-path",
            "",
            "--preserve-paths-csv",
            "data",
            "--health-check-type",
            "none",
            "--health-check-path",
            "",
            "--repo-root",
            str(root),
        ]
        if command_overrides:
            cmd.extend(command_overrides)
        return subprocess.run(cmd, check=False, capture_output=True, text=True)

    def test_wrapper_success_writes_apply_ok_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = self._run_wrapper(root, "sess-ok", [])
            self.assertEqual(result.returncode, 0, msg=result.stdout + result.stderr)
            journal = json.loads(
                (root / "data" / "update" / "session-sess-ok.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(journal.get("phase"), "apply")
            self.assertEqual(journal.get("status"), "ok")
            self.assertFalse((root / "data" / "update" / "last-run.json").exists())

    def test_wrapper_lock_conflict_returns_failed_lock_phase(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lock_dir = root / "data" / "update" / "updater.lock.d"
            lock_dir.mkdir(parents=True, exist_ok=True)
            result = self._run_wrapper(root, "sess-lock", [])
            self.assertEqual(result.returncode, 7, msg=result.stdout + result.stderr)
            journal = json.loads(
                (root / "data" / "update" / "last-run.json").read_text(encoding="utf-8")
            )
            self.assertEqual(journal.get("phase"), "lock")
            self.assertEqual(journal.get("status"), "failed")
            self.assertEqual(journal.get("detail"), "lock_active")

    def test_wrapper_health_failure_rolls_back(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root / "app" / "current"
            target.mkdir(parents=True, exist_ok=True)
            (target / "keep.txt").write_text("old", encoding="utf-8")
            # no health.txt in payload -> health check fails and rollback should restore old file
            result = self._run_wrapper(
                root,
                "sess-rb",
                [
                    "--install-mode",
                    "directory_swap",
                    "--install-target-path",
                    str(target),
                    "--health-check-type",
                    "file_exists",
                    "--health-check-path",
                    "health.txt",
                ],
            )
            self.assertEqual(result.returncode, 11, msg=result.stdout + result.stderr)
            self.assertEqual((target / "keep.txt").read_text(encoding="utf-8"), "old")
            journal = json.loads(
                (root / "data" / "update" / "session-sess-rb.json").read_text(
                    encoding="utf-8"
                )
            )
            self.assertEqual(journal.get("phase"), "rollback")
            self.assertEqual(journal.get("status"), "ok")

    def test_prepare_detects_interrupted_last_run_journal(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            journal_dir = root / "data" / "update"
            journal_dir.mkdir(parents=True, exist_ok=True)
            (journal_dir / "last-run.json").write_text(
                json.dumps(
                    {
                        "session_id": "sess-int",
                        "phase": "backup",
                        "status": "ok",
                        "detail": "backup_created",
                        "install_mode": "directory_swap",
                        "install_target_path": "app/current",
                        "target_version": "9.9.9",
                    }
                ),
                encoding="utf-8",
            )
            app = Application(AppConfig(bind_port=0))
            try:
                with patch("src.core.service.app.Path.cwd", return_value=root):
                    payload = app._app_shutdown_prepare()  # noqa: SLF001
                self.assertEqual(payload["phase"], "recovery_required")
                self.assertTrue(payload["recovery_required"])
                self.assertEqual(payload["recovery_session_id"], "sess-int")
            finally:
                app._server.server_close()  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
