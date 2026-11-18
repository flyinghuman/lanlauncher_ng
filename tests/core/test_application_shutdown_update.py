"""Tests for shutdown-time update session flow."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from src.core.config.loader import AppConfig
from src.core.service.app import Application
from src.core.service.feature_flags import FeatureFlags
from src.core.version import APP_VERSION

_TEST_PRIVATE_KEY_N = 145401073256137295776278674787625589014953316614149804072592752664357246043371100153164744616188694236366580281924421328424722775037085942563427524787329447488179653044902628983060972941693527813403274266776850649125155127785567213041180558483440639455204121749846718441140940467403481609908746345061884147271
_TEST_PRIVATE_KEY_D = 135681340861686260593162620127745098521422784546972632526107120892647386041906144635350155206183313009738538287095379873371413797246868607098417286508291777388154471908413932809346827638791078821032923652413688745966711833042943352527934630736266231182433279921648544849680876451729714554857222066145202710849
_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")


class ApplicationShutdownUpdateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._key_patch = patch.dict(
            "src.core.service.app.UPDATE_MANIFEST_PUBLIC_KEYS",
            {"llng-root-2026": (_TEST_PRIVATE_KEY_N, 65537)},
            clear=False,
        )
        cls._key_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._key_patch.stop()

    class _Platform:
        def __init__(self, name: str) -> None:
            self._name = name

        def platform_name(self) -> str:
            return self._name

    class _ScannerStats:
        def __init__(self, scanned: int, installed: int, missing: int) -> None:
            self.scanned = scanned
            self.installed = installed
            self.missing = missing

    class _Scanner:
        def __init__(self, exc: Exception | None = None) -> None:
            self.exc = exc
            self.calls = 0

        def scan(self, force: bool = False):  # noqa: ANN001
            _ = force
            self.calls += 1
            if self.exc is not None:
                raise self.exc
            return ApplicationShutdownUpdateTests._ScannerStats(3, 2, 1)

    def _canonical_manifest_bytes(self, payload: dict) -> bytes:
        unsigned_payload = {
            key: value for key, value in payload.items() if key != "signature"
        }
        return json.dumps(
            unsigned_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")

    def _sign_manifest(self, payload: dict) -> str:
        signed_bytes = self._canonical_manifest_bytes(payload)
        digest = hashlib.sha256(signed_bytes).digest()
        digest_info = _SHA256_DIGEST_INFO_PREFIX + digest
        key_size = (_TEST_PRIVATE_KEY_N.bit_length() + 7) // 8
        padding_size = key_size - len(digest_info) - 3
        em = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
        message_int = int.from_bytes(em, byteorder="big")
        signature_int = pow(message_int, _TEST_PRIVATE_KEY_D, _TEST_PRIVATE_KEY_N)
        signature = signature_int.to_bytes(key_size, byteorder="big")
        return base64.b64encode(signature).decode("ascii")

    def test_prepare_reports_ready_when_manifest_has_newer_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir(parents=True, exist_ok=True)
            payload_file = library / "ng_provider" / "payload.bin"
            payload_file.parent.mkdir(parents=True, exist_ok=True)
            payload_file.write_bytes(b"demo-payload")
            payload_sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()
            manifest = library / "ng_provider" / "update-manifest.json"
            manifest_payload = {
                "version": "9999.0.0",
                "payload": {
                    "path": "payload.bin",
                    "sha256": payload_sha,
                },
            }
            manifest_payload["signature"] = {
                "key_id": "llng-root-2026",
                "value": self._sign_manifest(manifest_payload),
            }
            manifest.write_text(
                json.dumps(manifest_payload, indent=2),
                encoding="utf-8",
            )

            app = Application(
                AppConfig(
                    bind_port=0,
                    library_path=str(library),
                    update_manifest_path="ng_provider/update-manifest.json",
                )
            )
            try:
                payload = app._app_shutdown_prepare()  # noqa: SLF001
                self.assertTrue(payload["accepted"])
                self.assertEqual(payload["phase"], "ready")
                self.assertTrue(payload["will_apply_update"])
                self.assertEqual(payload["target_version"], "9999.0.0")
                self.assertEqual(payload["current_version"], APP_VERSION)
                self.assertTrue(str(payload["payload_path"]).endswith("payload.bin"))
                self.assertEqual(payload["payload_sha256"], payload_sha)
                self.assertEqual(payload["install_mode"], "noop")
                self.assertEqual(payload["install_target_path"], "")
                self.assertEqual(payload["preserve_paths"], ["data"])
                self.assertEqual(payload["health_check_type"], "none")
                self.assertEqual(payload["health_check_path"], "")
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_prepare_stops_without_update_when_manifest_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir(parents=True, exist_ok=True)
            app = Application(
                AppConfig(
                    bind_port=0,
                    library_path=str(library),
                    update_manifest_path="ng_provider/update-manifest.json",
                )
            )
            try:
                payload = app._app_shutdown_prepare()  # noqa: SLF001
                self.assertEqual(payload["phase"], "no_update")
                self.assertFalse(payload["will_apply_update"])
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_apply_rejects_unknown_session(self) -> None:
        app = Application(AppConfig(bind_port=0))
        try:
            payload = app._app_shutdown_apply("missing")  # noqa: SLF001
            self.assertFalse(payload["accepted"])
            self.assertEqual(payload["message"], "shutdown_update_session_missing")
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_prepare_detects_interrupted_journal_and_requires_recovery(self) -> None:
        app = Application(AppConfig(bind_port=0))
        interrupted = {
            "session_id": "sess-int-1",
            "phase": "swap",
            "status": "ok",
            "detail": "directory_swap_complete",
            "manifest_path": "/tmp/update-manifest.json",
            "payload_path": "/tmp/update.tar.gz",
            "payload_sha256": "c" * 64,
            "install_mode": "directory_swap",
            "install_target_path": "app/current",
            "preserve_paths_csv": "data",
            "health_check_type": "file_exists",
            "health_check_path": "run.sh",
            "target_version": "9.9.9",
        }
        try:
            with patch.object(
                app, "_load_last_shutdown_update_journal", return_value=interrupted
            ):
                payload = app._app_shutdown_prepare()  # noqa: SLF001
            self.assertEqual(payload["phase"], "recovery_required")
            self.assertTrue(payload["recovery_required"])
            self.assertEqual(payload["recovery_session_id"], "sess-int-1")
            self.assertEqual(payload["session_id"], "sess-int-1")
            self.assertEqual(payload["install_mode"], "directory_swap")
            self.assertEqual(payload["health_check_type"], "file_exists")
            self.assertIn(
                "interrupted update session detected", payload["console_lines"][-1]
            )
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_prepare_ignores_stage_only_journal_for_recovery(self) -> None:
        app = Application(AppConfig(bind_port=0))
        stage_only = {
            "session_id": "sess-stage-only",
            "phase": "stage",
            "status": "ok",
            "detail": "payload_staged",
            "install_mode": "directory_swap",
            "install_target_path": "app/current",
        }
        try:
            with (
                patch.object(
                    app, "_load_last_shutdown_update_journal", return_value=stage_only
                ),
                patch.object(
                    app,
                    "_resolve_shutdown_update_candidate",
                    return_value={
                        "ok": True,
                        "update_available": False,
                        "target_version": "",
                        "manifest_path": "",
                        "payload_path": "",
                        "payload_sha256": "",
                        "message": "shutdown_update_manifest_missing",
                    },
                ),
            ):
                payload = app._app_shutdown_prepare()  # noqa: SLF001
            self.assertNotEqual(payload["phase"], "recovery_required")
            self.assertFalse(payload.get("recovery_required", False))
            self.assertEqual(payload["phase"], "no_update")
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_prepare_ignores_recovery_when_interrupted_target_is_not_newer(
        self,
    ) -> None:
        app = Application(AppConfig(bind_port=0))
        interrupted = {
            "session_id": "sess-stale-target",
            "phase": "swap",
            "status": "ok",
            "detail": "directory_swap_complete",
            "install_mode": "directory_swap",
            "install_target_path": "app/current",
            "target_version": APP_VERSION,
        }
        candidate = {
            "ok": True,
            "update_available": True,
            "target_version": "9.9.9",
            "manifest_path": "/tmp/update-manifest.json",
            "payload_path": "/tmp/update.tar.gz",
            "payload_sha256": "d" * 64,
            "install_mode": "directory_swap",
            "install_target_path": "/tmp/app",
            "preserve_paths": ["data"],
            "health_check_type": "none",
            "health_check_path": "",
            "message": "shutdown_update_checked",
        }
        try:
            with (
                patch.object(
                    app, "_load_last_shutdown_update_journal", return_value=interrupted
                ),
                patch.object(
                    app, "_resolve_shutdown_update_candidate", return_value=candidate
                ),
            ):
                payload = app._app_shutdown_prepare()  # noqa: SLF001
            self.assertEqual(payload["phase"], "ready")
            self.assertEqual(payload["target_version"], "9.9.9")
            self.assertFalse(payload.get("recovery_required", False))
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_prepare_prefers_newer_candidate_over_interrupted_recovery(self) -> None:
        app = Application(AppConfig(bind_port=0))
        interrupted = {
            "session_id": "sess-old-recovery",
            "phase": "backup",
            "status": "ok",
            "detail": "backup_created",
            "install_mode": "directory_swap",
            "install_target_path": "app/current",
            "target_version": "0.1.8",
        }
        candidate = {
            "ok": True,
            "update_available": True,
            "target_version": "0.3.0",
            "manifest_path": "/tmp/update-manifest.json",
            "payload_path": "/tmp/update-030.tar.gz",
            "payload_sha256": "e" * 64,
            "install_mode": "directory_swap",
            "install_target_path": "/tmp/app",
            "preserve_paths": ["data"],
            "health_check_type": "none",
            "health_check_path": "",
            "message": "shutdown_update_checked",
        }
        try:
            with (
                patch.object(
                    app, "_load_last_shutdown_update_journal", return_value=interrupted
                ),
                patch.object(
                    app, "_resolve_shutdown_update_candidate", return_value=candidate
                ),
            ):
                payload = app._app_shutdown_prepare()  # noqa: SLF001
            self.assertEqual(payload["phase"], "ready")
            self.assertEqual(payload["target_version"], "0.3.0")
            self.assertFalse(payload.get("recovery_required", False))
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_prepare_rebuilds_state_when_previous_phase_was_recovery_required(
        self,
    ) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.shutdown_update_state = {  # noqa: SLF001
            "accepted": True,
            "phase": "recovery_required",
            "session_id": "old-recovery",
            "recovery_required": True,
            "recovery_session_id": "old-recovery",
            "target_version": "0.1.8",
            "console_lines": [],
        }
        candidate = {
            "ok": True,
            "update_available": True,
            "target_version": "0.3.0",
            "manifest_path": "/tmp/update-manifest.json",
            "payload_path": "/tmp/update-030.tar.gz",
            "payload_sha256": "f" * 64,
            "install_mode": "directory_swap",
            "install_target_path": "/tmp/app",
            "preserve_paths": ["data"],
            "health_check_type": "none",
            "health_check_path": "",
            "message": "shutdown_update_checked",
        }
        try:
            with (
                patch.object(
                    app, "_load_last_shutdown_update_journal", return_value=None
                ),
                patch.object(
                    app, "_resolve_shutdown_update_candidate", return_value=candidate
                ),
            ):
                payload = app._app_shutdown_prepare()  # noqa: SLF001
            self.assertEqual(payload["phase"], "ready")
            self.assertEqual(payload["target_version"], "0.3.0")
            self.assertFalse(payload.get("recovery_required", False))
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_prepare_ignores_interrupted_journal_when_recovery_flag_disabled(
        self,
    ) -> None:
        app = Application(AppConfig(bind_port=0))
        app._feature_flags = FeatureFlags(  # noqa: SLF001
            {"shutdown_update_recovery": False},
            "tests",
        )
        interrupted = {
            "session_id": "sess-disabled",
            "phase": "backup",
            "status": "ok",
            "detail": "backup_created",
            "install_mode": "directory_swap",
            "install_target_path": "app/current",
            "target_version": "9.9.9",
        }
        candidate = {
            "ok": True,
            "update_available": False,
            "target_version": "",
            "manifest_path": "",
            "payload_path": "",
            "payload_sha256": "",
            "message": "shutdown_update_manifest_missing",
        }
        try:
            with (
                patch.object(
                    app, "_load_last_shutdown_update_journal", return_value=interrupted
                ),
                patch.object(
                    app, "_resolve_shutdown_update_candidate", return_value=candidate
                ),
            ):
                payload = app._app_shutdown_prepare()  # noqa: SLF001
            self.assertEqual(payload["phase"], "no_update")
            self.assertFalse(payload.get("recovery_required", False))
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_apply_requires_resume_or_abort_action_when_recovery_pending(self) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.shutdown_update_state = {  # noqa: SLF001
            "accepted": True,
            "session_id": "sess-recovery-a",
            "phase": "recovery_required",
            "recovery_required": True,
            "recovery_session_id": "sess-recovery-a",
            "console_lines": [],
        }
        try:
            payload = app._app_shutdown_apply("sess-recovery-a", "start")  # noqa: SLF001
            self.assertFalse(payload["accepted"])
            self.assertEqual(
                payload["message"], "shutdown_update_recovery_action_required"
            )
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_apply_abort_recovery_sets_aborted_terminal_state(self) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.shutdown_update_state = {  # noqa: SLF001
            "accepted": True,
            "session_id": "sess-recovery-b",
            "phase": "recovery_required",
            "recovery_required": True,
            "recovery_session_id": "sess-recovery-b",
            "install_target_path": "app/current",
            "console_lines": [],
        }
        try:
            with (
                patch.object(
                    app,
                    "_abort_shutdown_update_recovery",
                    return_value={
                        "ok": True,
                        "message": "shutdown_update_recovery_aborted",
                    },
                ),
                patch("src.core.service.app.Thread"),
            ):
                payload = app._app_shutdown_apply("sess-recovery-b", "abort")  # noqa: SLF001
            self.assertTrue(payload["accepted"])
            self.assertEqual(payload["phase"], "aborted")
            self.assertFalse(payload["recovery_required"])
            self.assertEqual(payload["recovery_action"], "abort")
            self.assertEqual(payload["message"], "shutdown_update_recovery_aborted")
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_apply_resume_recovery_starts_updater_thread(self) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.shutdown_update_state = {  # noqa: SLF001
            "accepted": True,
            "session_id": "sess-recovery-c",
            "phase": "recovery_required",
            "recovery_required": True,
            "recovery_session_id": "sess-recovery-c",
            "console_lines": [],
        }
        try:
            thread_calls: list[str] = []

            class _Thread:
                def __init__(self, target, daemon=True):  # noqa: ANN001
                    self._target = target
                    _ = daemon

                def start(self) -> None:
                    thread_calls.append("started")

            with patch("src.core.service.app.Thread", side_effect=_Thread):
                payload = app._app_shutdown_apply("sess-recovery-c", "resume")  # noqa: SLF001
            self.assertEqual(payload["phase"], "running")
            self.assertEqual(payload["recovery_action"], "resume")
            self.assertFalse(payload["recovery_required"])
            self.assertEqual(thread_calls, ["started"])
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_prepare_rejects_payload_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir(parents=True, exist_ok=True)
            payload_file = library / "ng_provider" / "payload.bin"
            payload_file.parent.mkdir(parents=True, exist_ok=True)
            payload_file.write_bytes(b"checksum-source")
            manifest = library / "ng_provider" / "update-manifest.json"
            manifest_payload = {
                "version": "9999.0.0",
                "payload": {
                    "path": "payload.bin",
                    "sha256": "0" * 64,
                },
            }
            manifest_payload["signature"] = {
                "key_id": "llng-root-2026",
                "value": self._sign_manifest(manifest_payload),
            }
            manifest.write_text(
                json.dumps(manifest_payload, indent=2),
                encoding="utf-8",
            )
            app = Application(
                AppConfig(
                    bind_port=0,
                    library_path=str(library),
                    update_manifest_path="ng_provider/update-manifest.json",
                )
            )
            try:
                payload = app._app_shutdown_prepare()  # noqa: SLF001
                self.assertEqual(payload["phase"], "error")
                self.assertEqual(
                    payload["message"], "shutdown_update_payload_checksum_mismatch"
                )
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_prepare_rejects_missing_signature(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir(parents=True, exist_ok=True)
            payload_file = library / "ng_provider" / "payload.bin"
            payload_file.parent.mkdir(parents=True, exist_ok=True)
            payload_file.write_bytes(b"payload")
            payload_sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()
            manifest = library / "ng_provider" / "update-manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "version": "9999.0.0",
                        "payload": {"path": "payload.bin", "sha256": payload_sha},
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            app = Application(
                AppConfig(
                    bind_port=0,
                    library_path=str(library),
                    update_manifest_path="ng_provider/update-manifest.json",
                )
            )
            try:
                payload = app._app_shutdown_prepare()  # noqa: SLF001
                self.assertEqual(payload["phase"], "error")
                self.assertEqual(
                    payload["message"], "shutdown_update_manifest_signature_missing"
                )
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_scan_install_state_skips_during_finalize_pending(self) -> None:
        app = Application(AppConfig(bind_port=0))
        scanner = self._Scanner()
        app._state.scanner = scanner  # noqa: SLF001
        app._state.shutdown_update_state = {  # noqa: SLF001
            "will_apply_update": True,
            "phase": "done",
        }
        try:
            payload = app._scan_install_state(force=True)  # noqa: SLF001
            self.assertEqual(payload, {"scanned": 0, "installed": 0, "missing": 0})
            self.assertEqual(scanner.calls, 0)
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_scan_install_state_handles_readonly_db_error(self) -> None:
        app = Application(AppConfig(bind_port=0))
        scanner = self._Scanner(
            sqlite3.OperationalError("attempt to write a readonly database")
        )
        app._state.scanner = scanner  # noqa: SLF001
        try:
            payload = app._scan_install_state(force=True)  # noqa: SLF001
            self.assertEqual(payload, {"scanned": 0, "installed": 0, "missing": 0})
            self.assertEqual(scanner.calls, 1)
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_apply_passes_session_and_payload_to_windows_updater(self) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.platform_adapter = self._Platform("windows")  # noqa: SLF001
        app._state.shutdown_update_state = {  # noqa: SLF001
            "session_id": "sess-42",
            "manifest_path": "C:/tmp/update-manifest.json",
            "payload_path": "C:/tmp/update.zip",
            "payload_sha256": "a" * 64,
            "target_version": "9.9.9",
            "health_check_type": "none",
            "health_check_path": "",
            "console_lines": [],
        }

        class _Proc:
            def __init__(self, cmd: list[str]) -> None:
                self.cmd = cmd
                self.stdout = iter(["ok\n"])

            def wait(self, timeout=None):  # noqa: ANN001
                _ = timeout
                return 0

        captured: dict[str, list[str]] = {}

        def _fake_popen(cmd, **kwargs):  # noqa: ANN001
            _ = kwargs
            captured["cmd"] = cmd
            return _Proc(cmd)

        try:
            with patch(
                "src.core.service.app.subprocess.Popen", side_effect=_fake_popen
            ):
                app._run_shutdown_update_apply()  # noqa: SLF001
            cmd = captured["cmd"]
            self.assertIn("-SessionId", cmd)
            self.assertIn("sess-42", cmd)
            self.assertIn("-PayloadPath", cmd)
            self.assertIn("C:/tmp/update.zip", cmd)
            self.assertIn("-PayloadSha256", cmd)
            self.assertIn("-InstallMode", cmd)
            self.assertIn("noop", cmd)
            self.assertIn("-InstallTargetPath", cmd)
            self.assertIn("-PreservePathsCsv", cmd)
            self.assertIn("-HealthCheckType", cmd)
            self.assertIn("-HealthCheckPath", cmd)
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_apply_detaches_windows_directory_swap_from_runtime_root(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            script_path = (
                runtime_root / "scripts" / "wrappers" / "windows" / "llng-updater.ps1"
            )
            script_path.parent.mkdir(parents=True, exist_ok=True)
            script_path.write_text("Write-Host test\n", encoding="utf-8")

            app = Application(AppConfig(bind_port=0))
            app._state.platform_adapter = self._Platform("windows")  # noqa: SLF001
            app._state.shutdown_update_state = {  # noqa: SLF001
                "session_id": "sess-detached",
                "manifest_path": "C:/tmp/update-manifest.json",
                "payload_path": "C:/tmp/update.zip",
                "payload_sha256": "a" * 64,
                "target_version": "9.9.9",
                "install_mode": "directory_swap",
                "install_target_path": str(runtime_root),
                "health_check_type": "none",
                "health_check_path": "",
                "console_lines": [],
            }
            captured: dict[str, object] = {}
            thread_calls: list[str] = []

            def _fake_popen(cmd, **kwargs):  # noqa: ANN001
                captured["cmd"] = cmd
                captured["kwargs"] = kwargs

                class _Proc:
                    stdout = None

                return _Proc()

            class _Thread:
                def __init__(self, target, daemon=True):  # noqa: ANN001
                    _ = target
                    _ = daemon

                def start(self) -> None:
                    thread_calls.append("started")

            try:
                with (
                    patch("src.core.service.app.Path.cwd", return_value=runtime_root),
                    patch.object(
                        app,
                        "_resolve_shutdown_updater_script_path",
                        return_value=script_path,
                    ),
                    patch(
                        "src.core.service.app.subprocess.Popen",
                        side_effect=_fake_popen,
                    ),
                    patch("src.core.service.app.Thread", side_effect=_Thread),
                ):
                    app._run_shutdown_update_apply()  # noqa: SLF001
                cmd = captured["cmd"]
                kwargs = captured["kwargs"]
                self.assertIn("-ParentProcessId", cmd)
                self.assertIn(str(os.getpid()), cmd)
                staged_script = Path(cmd[cmd.index("-File") + 1])
                self.assertNotEqual(staged_script, script_path)
                self.assertFalse(
                    str(staged_script.resolve(strict=False)).startswith(
                        str(runtime_root.resolve(strict=False))
                    )
                )
                self.assertEqual(
                    kwargs["creationflags"],
                    getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
                )
                self.assertEqual(kwargs["cwd"], str(staged_script.parent))
                state = app._state.shutdown_update_state  # noqa: SLF001
                self.assertEqual(state["phase"], "handoff")
                self.assertTrue(state["detached_handoff_pending"])
                self.assertEqual(state["frontend_auto_close_seconds"], 5)
                self.assertEqual(thread_calls, ["started"])
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_shutdown_apply_marks_windows_handoff_for_frontend_countdown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            runtime_root = Path(tmp) / "runtime"
            runtime_root.mkdir(parents=True, exist_ok=True)
            app = Application(AppConfig(bind_port=0))
            app._state.platform_adapter = self._Platform("windows")  # noqa: SLF001
            app._state.shutdown_update_state = {  # noqa: SLF001
                "accepted": True,
                "session_id": "sess-apply-handoff",
                "phase": "ready",
                "install_mode": "directory_swap",
                "install_target_path": str(runtime_root),
                "console_lines": [],
            }

            class _Thread:
                def __init__(self, target, daemon=True):  # noqa: ANN001
                    _ = target
                    _ = daemon

                def start(self) -> None:
                    return None

            try:
                with (
                    patch("src.core.service.app.Path.cwd", return_value=runtime_root),
                    patch("src.core.service.app.Thread", side_effect=_Thread),
                ):
                    payload = app._app_shutdown_apply("sess-apply-handoff")  # noqa: SLF001
                self.assertEqual(payload["phase"], "running")
                self.assertTrue(payload["detached_handoff_pending"])
                self.assertEqual(payload["frontend_auto_close_seconds"], 5)
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_apply_passes_session_and_payload_to_linux_updater(self) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.platform_adapter = self._Platform("linux")  # noqa: SLF001
        app._state.shutdown_update_state = {  # noqa: SLF001
            "session_id": "sess-77",
            "manifest_path": "/tmp/update-manifest.json",
            "payload_path": "/tmp/update.tar.gz",
            "payload_sha256": "b" * 64,
            "target_version": "9.9.9",
            "health_check_type": "none",
            "health_check_path": "",
            "console_lines": [],
        }

        class _Proc:
            def __init__(self, cmd: list[str]) -> None:
                self.cmd = cmd
                self.stdout = iter(["ok\n"])

            def wait(self, timeout=None):  # noqa: ANN001
                _ = timeout
                return 0

        captured: dict[str, list[str]] = {}

        def _fake_popen(cmd, **kwargs):  # noqa: ANN001
            _ = kwargs
            captured["cmd"] = cmd
            return _Proc(cmd)

        try:
            with patch(
                "src.core.service.app.subprocess.Popen", side_effect=_fake_popen
            ):
                app._run_shutdown_update_apply()  # noqa: SLF001
            cmd = captured["cmd"]
            self.assertIn("--session-id", cmd)
            self.assertIn("sess-77", cmd)
            self.assertIn("--payload-path", cmd)
            self.assertIn("/tmp/update.tar.gz", cmd)
            self.assertIn("--payload-sha256", cmd)
            self.assertIn("--install-mode", cmd)
            self.assertIn("noop", cmd)
            self.assertIn("--install-target-path", cmd)
            self.assertIn("--preserve-paths-csv", cmd)
            self.assertIn("--health-check-type", cmd)
            self.assertIn("--health-check-path", cmd)
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_prepare_rejects_invalid_install_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir(parents=True, exist_ok=True)
            payload_file = library / "ng_provider" / "payload.bin"
            payload_file.parent.mkdir(parents=True, exist_ok=True)
            payload_file.write_bytes(b"demo-payload")
            payload_sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()
            manifest = library / "ng_provider" / "update-manifest.json"
            manifest_payload = {
                "version": "9999.0.0",
                "payload": {"path": "payload.bin", "sha256": payload_sha},
                "install": {"mode": "bad-mode"},
            }
            manifest_payload["signature"] = {
                "key_id": "llng-root-2026",
                "value": self._sign_manifest(manifest_payload),
            }
            manifest.write_text(
                json.dumps(manifest_payload, indent=2), encoding="utf-8"
            )
            app = Application(
                AppConfig(
                    bind_port=0,
                    library_path=str(library),
                    update_manifest_path="ng_provider/update-manifest.json",
                )
            )
            try:
                payload = app._app_shutdown_prepare()  # noqa: SLF001
                self.assertEqual(payload["phase"], "error")
                self.assertEqual(
                    payload["message"], "shutdown_update_manifest_install_mode_invalid"
                )
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_prepare_accepts_directory_swap_install_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir(parents=True, exist_ok=True)
            payload_dir = library / "ng_provider" / "payload-dir"
            payload_dir.mkdir(parents=True, exist_ok=True)
            (payload_dir / "file.txt").write_text("ok", encoding="utf-8")
            payload_bytes = b"".join(
                p.read_bytes() for p in sorted(payload_dir.rglob("*")) if p.is_file()
            )
            payload_sha = hashlib.sha256(payload_bytes).hexdigest()
            # For candidate validation we hash the actual payload path bytes.
            # directory payload hashing is validated in wrapper phase; backend expects file checksum.
            payload_file = library / "ng_provider" / "payload.tar"
            payload_file.write_bytes(b"payload-archive")
            payload_sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()
            manifest = library / "ng_provider" / "update-manifest.json"
            manifest_payload = {
                "version": "9999.0.0",
                "payload": {"path": "payload.tar", "sha256": payload_sha},
                "install": {
                    "mode": "directory_swap",
                    "target_path": "app/current",
                    "preserve_paths": ["data", "../bad", "/abs"],
                },
            }
            manifest_payload["signature"] = {
                "key_id": "llng-root-2026",
                "value": self._sign_manifest(manifest_payload),
            }
            manifest.write_text(
                json.dumps(manifest_payload, indent=2), encoding="utf-8"
            )
            app = Application(
                AppConfig(
                    bind_port=0,
                    library_path=str(library),
                    update_manifest_path="ng_provider/update-manifest.json",
                )
            )
            try:
                runtime_root = Path(tmp) / "runtime-no-fallback"
                with patch("src.core.service.app.Path.cwd", return_value=runtime_root):
                    payload = app._app_shutdown_prepare()  # noqa: SLF001
                self.assertEqual(payload["phase"], "ready")
                self.assertEqual(payload["install_mode"], "directory_swap")
                self.assertEqual(
                    payload["install_target_path"],
                    str((runtime_root / "app" / "current").resolve(strict=False)),
                )
                self.assertEqual(payload["preserve_paths"], ["data"])
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_prepare_falls_back_to_install_root_for_legacy_app_current_target(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir(parents=True, exist_ok=True)
            payload_file = library / "ng_provider" / "payload.tar"
            payload_file.parent.mkdir(parents=True, exist_ok=True)
            payload_file.write_bytes(b"payload-archive")
            payload_sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()
            manifest = library / "ng_provider" / "update-manifest.json"
            manifest_payload = {
                "version": "9999.0.0",
                "payload": {"path": "payload.tar", "sha256": payload_sha},
                "install": {"mode": "directory_swap", "target_path": "app/current"},
            }
            manifest_payload["signature"] = {
                "key_id": "llng-root-2026",
                "value": self._sign_manifest(manifest_payload),
            }
            manifest.write_text(
                json.dumps(manifest_payload, indent=2), encoding="utf-8"
            )
            runtime_root = Path(tmp) / "runtime"
            (runtime_root / "app").mkdir(parents=True, exist_ok=True)
            (runtime_root / "run.bat").write_text("@echo off\n", encoding="utf-8")
            app = Application(
                AppConfig(
                    bind_port=0,
                    library_path=str(library),
                    update_manifest_path="ng_provider/update-manifest.json",
                )
            )
            try:
                with patch("src.core.service.app.Path.cwd", return_value=runtime_root):
                    payload = app._app_shutdown_prepare()  # noqa: SLF001
                self.assertEqual(payload["phase"], "ready")
                self.assertEqual(
                    payload["install_target_path"],
                    str(runtime_root.resolve(strict=False)),
                )
                self.assertIn(
                    "install target app/current not found; using install root instead",
                    payload["console_lines"],
                )
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_prepare_rejects_invalid_health_check(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            library = Path(tmp) / "library"
            library.mkdir(parents=True, exist_ok=True)
            payload_file = library / "ng_provider" / "payload.tar"
            payload_file.parent.mkdir(parents=True, exist_ok=True)
            payload_file.write_bytes(b"payload-archive")
            payload_sha = hashlib.sha256(payload_file.read_bytes()).hexdigest()
            manifest = library / "ng_provider" / "update-manifest.json"
            manifest_payload = {
                "version": "9999.0.0",
                "payload": {"path": "payload.tar", "sha256": payload_sha},
                "health_check": {"type": "unknown"},
            }
            manifest_payload["signature"] = {
                "key_id": "llng-root-2026",
                "value": self._sign_manifest(manifest_payload),
            }
            manifest.write_text(
                json.dumps(manifest_payload, indent=2), encoding="utf-8"
            )
            app = Application(
                AppConfig(
                    bind_port=0,
                    library_path=str(library),
                    update_manifest_path="ng_provider/update-manifest.json",
                )
            )
            try:
                payload = app._app_shutdown_prepare()  # noqa: SLF001
                self.assertEqual(payload["phase"], "error")
                self.assertEqual(
                    payload["message"], "shutdown_update_manifest_health_check_invalid"
                )
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_apply_reads_journal_fields_into_shutdown_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Application(AppConfig(bind_port=0))
            app._state.platform_adapter = self._Platform("windows")  # noqa: SLF001
            app._state.shutdown_update_state = {  # noqa: SLF001
                "session_id": "sess-j1",
                "manifest_path": "C:/tmp/update-manifest.json",
                "payload_path": "C:/tmp/update.zip",
                "payload_sha256": "a" * 64,
                "target_version": "9.9.9",
                "health_check_type": "none",
                "health_check_path": "",
                "console_lines": [],
            }
            journal_path = Path(tmp) / "session-sess-j1.json"
            journal_path.write_text(
                json.dumps(
                    {
                        "phase": "swap",
                        "status": "ok",
                        "detail": "directory_swap_complete",
                    }
                ),
                encoding="utf-8",
            )

            class _Proc:
                def __init__(self) -> None:
                    self.stdout = iter([])

                def wait(self, timeout=None):  # noqa: ANN001
                    _ = timeout
                    return 0

            try:
                with (
                    patch(
                        "src.core.service.app.subprocess.Popen",
                        return_value=_Proc(),
                    ),
                    patch.object(
                        app,
                        "_shutdown_update_journal_path",
                        return_value=journal_path,
                    ),
                ):
                    app._run_shutdown_update_apply()  # noqa: SLF001
                state = app._state.shutdown_update_state  # noqa: SLF001
                self.assertEqual(state["updater_phase"], "swap")
                self.assertEqual(state["updater_status"], "ok")
                self.assertEqual(state["updater_detail"], "directory_swap_complete")
                self.assertFalse(state["rollback_performed"])
                self.assertEqual(state["updater_result_code"], "ok")
                self.assertEqual(state["updater_exit_code"], 0)
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_apply_sets_rolled_back_message_when_exit_nonzero_and_rollback_journal(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Application(AppConfig(bind_port=0))
            app._state.platform_adapter = self._Platform("windows")  # noqa: SLF001
            app._state.shutdown_update_state = {  # noqa: SLF001
                "session_id": "sess-j2",
                "manifest_path": "C:/tmp/update-manifest.json",
                "payload_path": "C:/tmp/update.zip",
                "payload_sha256": "a" * 64,
                "target_version": "9.9.9",
                "health_check_type": "none",
                "health_check_path": "",
                "console_lines": [],
            }
            journal_path = Path(tmp) / "session-sess-j2.json"
            journal_path.write_text(
                json.dumps(
                    {
                        "phase": "rollback",
                        "status": "ok",
                        "detail": "rollback_complete_after_health",
                    }
                ),
                encoding="utf-8",
            )

            class _Proc:
                def __init__(self) -> None:
                    self.stdout = iter([])

                def wait(self, timeout=None):  # noqa: ANN001
                    _ = timeout
                    return 11

            try:
                with (
                    patch(
                        "src.core.service.app.subprocess.Popen",
                        return_value=_Proc(),
                    ),
                    patch.object(
                        app,
                        "_shutdown_update_journal_path",
                        return_value=journal_path,
                    ),
                ):
                    app._run_shutdown_update_apply()  # noqa: SLF001
                state = app._state.shutdown_update_state  # noqa: SLF001
                self.assertEqual(state["phase"], "failed")
                self.assertEqual(
                    state["message"], "shutdown_update_apply_failed_rolled_back"
                )
                self.assertTrue(state["rollback_performed"])
                self.assertEqual(state["updater_phase"], "rollback")
                self.assertEqual(state["updater_result_code"], "rolled_back")
                self.assertEqual(state["updater_exit_code"], 11)
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_apply_sets_timeout_exit_code_on_timeout(self) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.platform_adapter = self._Platform("windows")  # noqa: SLF001
        app._state.shutdown_update_state = {  # noqa: SLF001
            "session_id": "sess-timeout",
            "manifest_path": "C:/tmp/update-manifest.json",
            "payload_path": "C:/tmp/update.zip",
            "payload_sha256": "a" * 64,
            "target_version": "9.9.9",
            "health_check_type": "none",
            "health_check_path": "",
            "console_lines": [],
        }

        class _Proc:
            def __init__(self) -> None:
                self.stdout = iter([])

            def wait(self, timeout=None):  # noqa: ANN001
                _ = timeout
                raise subprocess.TimeoutExpired(cmd=["updater"], timeout=180)

        try:
            with patch("src.core.service.app.subprocess.Popen", return_value=_Proc()):
                app._run_shutdown_update_apply()  # noqa: SLF001
            state = app._state.shutdown_update_state  # noqa: SLF001
            self.assertEqual(state["phase"], "failed")
            self.assertEqual(state["updater_result_code"], "timeout")
            self.assertEqual(state["updater_exit_code"], -3)
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_apply_linux_exit12_without_journal_maps_to_elevation_failed(self) -> None:
        app = Application(AppConfig(bind_port=0))
        app._state.platform_adapter = self._Platform("linux")  # noqa: SLF001
        app._state.shutdown_update_state = {  # noqa: SLF001
            "session_id": "sess-linux-elev",
            "manifest_path": "/tmp/update-manifest.json",
            "payload_path": "/tmp/update.tar.gz",
            "payload_sha256": "a" * 64,
            "target_version": "9.9.9",
            "health_check_type": "none",
            "health_check_path": "",
            "console_lines": [],
        }

        class _Proc:
            def __init__(self) -> None:
                self.stdout = iter([])

            def wait(self, timeout=None):  # noqa: ANN001
                _ = timeout
                return 12

        try:
            with (
                patch("src.core.service.app.subprocess.Popen", return_value=_Proc()),
                patch.object(app, "_load_shutdown_update_journal", return_value=None),
            ):
                app._run_shutdown_update_apply()  # noqa: SLF001
            state = app._state.shutdown_update_state  # noqa: SLF001
            self.assertEqual(state["phase"], "failed")
            self.assertEqual(state["updater_result_code"], "elevation_failed")
            self.assertEqual(state["updater_exit_code"], 12)
        finally:
            app._server.server_close()  # noqa: SLF001

    def test_manual_rollback_restores_latest_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Application(AppConfig(bind_port=0))
            try:
                base = Path(tmp)
                target = base / "app" / "current"
                target.mkdir(parents=True, exist_ok=True)
                (target / "version.txt").write_text("new", encoding="utf-8")

                backup_current = (
                    base / "data" / "update" / "backup" / "sess-r1" / "current"
                )
                backup_current.mkdir(parents=True, exist_ok=True)
                (backup_current / "version.txt").write_text("old", encoding="utf-8")

                journal = base / "data" / "update" / "session-sess-r1.json"
                journal.parent.mkdir(parents=True, exist_ok=True)
                journal.write_text(
                    json.dumps(
                        {
                            "install_mode": "directory_swap",
                            "install_target_path": "app/current",
                        }
                    ),
                    encoding="utf-8",
                )

                with patch("src.core.service.app.Path.cwd", return_value=base):
                    result = app._app_update_rollback()  # noqa: SLF001

                self.assertTrue(result["ok"])
                self.assertEqual(result["message"], "update_rollback_applied")
                self.assertFalse(backup_current.exists())
                self.assertTrue((target / "version.txt").exists())
                self.assertEqual(
                    (target / "version.txt").read_text(encoding="utf-8"), "old"
                )
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_manual_rollback_returns_not_available_without_backup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            app = Application(AppConfig(bind_port=0))
            try:
                with patch("src.core.service.app.Path.cwd", return_value=Path(tmp)):
                    result = app._app_update_rollback()  # noqa: SLF001
                self.assertFalse(result["ok"])
                self.assertEqual(result["message"], "update_rollback_backup_missing")
            finally:
                app._server.server_close()  # noqa: SLF001

    def test_map_updater_result_code_handles_elevation_failure(self) -> None:
        app = Application(AppConfig(bind_port=0))
        try:
            code = app._map_updater_result_code(  # noqa: SLF001
                phase="elevate",
                status="failed",
                detail="elevation_denied",
                rollback_performed=False,
            )
            self.assertEqual(code, "elevation_failed")
        finally:
            app._server.server_close()  # noqa: SLF001


if __name__ == "__main__":
    unittest.main()
