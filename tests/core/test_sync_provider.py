"""Tests for Resilio sync provider internals."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from src.core.sync.resilio_provider import (
    ResilioSyncProvider,
    _parse_json_or_jsonp,
    persist_runtime_paths,
)
from src.core.sync.provider import SyncStatus


class ResilioProviderTests(unittest.TestCase):
    def test_parse_json_payload(self) -> None:
        payload = _parse_json_or_jsonp('{"download": 100, "upload": 50}')
        self.assertEqual(payload["download"], 100)

    def test_parse_jsonp_payload(self) -> None:
        payload = _parse_json_or_jsonp('callback({"download": 10, "upload": 5})')
        self.assertEqual(payload["upload"], 5)

    def test_parse_json_array_payload(self) -> None:
        payload = _parse_json_or_jsonp(
            '[{"dir":"D:/LAN/demo","size":100,"total_size":100}]'
        )
        self.assertIsInstance(payload, list)
        assert isinstance(payload, list)
        self.assertEqual(payload[0]["dir"], "D:/LAN/demo")

    def test_cleanup_stale_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            pid_path = Path(tmp) / "rslsync.pid"
            # Use a likely non-existing pid to represent stale state.
            pid_path.write_text("999999", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path="vendor/bin/windows-amd64/btsync.exe",
                config_path="config/resilio.json",
                pid_path=str(pid_path),
                log_path=str(Path(tmp) / "resilio.log"),
                license_key_path=str(Path(tmp) / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            provider._cleanup_stale_pid()  # noqa: SLF001 test internal robustness helper
            self.assertFalse(pid_path.exists())

    def test_cleanup_removes_pid_file_for_unrelated_reused_linux_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            pid_path = base / "rslsync.pid"
            pid_path.write_text("12345", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path=str(base / "rslsync"),
                config_path=str(base / "config.json"),
                pid_path=str(pid_path),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch("src.core.sync.resilio_provider._pid_running", return_value=True),
                patch.object(
                    provider,
                    "_linux_process_argv",
                    return_value=["/usr/bin/python3", "-m", "http.server"],
                ),
            ):
                provider._cleanup_stale_pid()  # noqa: SLF001

            self.assertFalse(pid_path.exists())

    def test_cleanup_removes_stale_storage_sync_pid_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            storage = base / "storage"
            storage.mkdir()
            storage_pid = storage / "sync.pid"
            storage_pid.write_text("12345", encoding="utf-8")
            cfg = base / "config.json"
            cfg.write_text(
                json.dumps({"storage_path": str(storage)}),
                encoding="utf-8",
            )

            provider = ResilioSyncProvider(
                binary_path=str(base / "rslsync"),
                config_path=str(cfg),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch("src.core.sync.resilio_provider._pid_running", return_value=False),
            ):
                provider._cleanup_stale_pid()  # noqa: SLF001

            self.assertFalse(storage_pid.exists())

    def test_windows_start_uses_absolute_config_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / "btsync.exe"
            binary.write_text("stub", encoding="utf-8")
            cfg = base / "config" / "resilio" / "config.json"
            cfg.parent.mkdir(parents=True)
            storage = (base / "sync-storage").resolve()
            cfg.write_text(
                f'{{"storage_path":"{storage.as_posix()}"}}', encoding="utf-8"
            )
            key = base / "llng.btskey"
            key.write_text("stub", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path=str(binary),
                config_path=str(cfg),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(key),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Windows",
                ),
                patch("src.core.sync.resilio_provider.subprocess.run") as mocked_run,
                patch(
                    "src.core.sync.resilio_provider.subprocess.Popen"
                ) as mocked_popen,
                patch.object(provider, "_is_api_reachable", return_value=False),
                patch.object(provider, "metrics", return_value=None),
                patch.object(provider, "_start_process_output_forwarders"),
            ):
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = ""
                mocked_run.return_value.stderr = ""
                mocked_popen.return_value.pid = 1234
                provider.start()

            args, kwargs = mocked_popen.call_args
            cmd = args[0]
            self.assertEqual(cmd[0], str(binary))
            self.assertEqual(
                cmd[1:], ["/minimized", "/config", str(cfg.resolve())]
            )
            self.assertEqual(kwargs.get("cwd"), str(base.resolve()))
            self.assertIsNone(kwargs.get("preexec_fn"))
            self.assertIn("stdout", kwargs)
            self.assertIn("stderr", kwargs)
            self.assertEqual(kwargs.get("stdout"), subprocess.PIPE)
            self.assertEqual(kwargs.get("stderr"), subprocess.PIPE)
            self.assertTrue(kwargs.get("text"))
            provider.stop()
            if provider._state.log_handle is not None:  # noqa: SLF001 test cleanup
                provider._state.log_handle.close()  # noqa: SLF001 test cleanup
                provider._state.log_handle = None  # noqa: SLF001 test cleanup

    def test_persist_runtime_paths_replaces_stale_absolute_paths_and_keeps_comments_parseable(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cfg = base / "config" / "resilio" / "config.json"
            cfg.parent.mkdir(parents=True)
            stale = str(base / "old-install" / "data" / "sync")
            cfg.write_text(
                "// managed by LANLauncherNG\n"
                + json.dumps(
                    {
                        "storage_path": stale,
                        "pid_file": stale + "/rslsync.pid",
                        "lanlauncher_library_path": "/games",
                        "webui": {"api_key": "k"},
                    }
                ),
                encoding="utf-8",
            )
            self.assertTrue(persist_runtime_paths(cfg, base))
            saved = json.loads(cfg.read_text(encoding="utf-8"))
            expected = (base / "data" / "sync").resolve()
            self.assertEqual(saved["storage_path"], str(expected))
            self.assertEqual(saved["pid_file"], str(expected / "rslsync.pid"))
            self.assertNotIn("lanlauncher_library_path", saved)
            self.assertEqual(saved["webui"]["api_key"], "k")
            self.assertTrue(expected.is_dir())
            self.assertFalse(persist_runtime_paths(cfg, base))
            self.assertEqual(sorted(p.name for p in cfg.parent.iterdir()), ["config.json"])

    def test_start_prepares_absolute_storage_and_pid_paths_before_bootstrap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / "btsync.exe"
            binary.write_text("stub", encoding="utf-8")
            cfg = base / "config" / "resilio" / "config.json"
            cfg.parent.mkdir(parents=True)
            cfg.write_text(
                json.dumps(
                    {
                        "storage_path": "data/sync",
                        "pid_file": "data/sync/rslsync.pid",
                        "webui": {"api_key": "test-key"},
                    }
                ),
                encoding="utf-8",
            )
            provider = ResilioSyncProvider(
                binary_path=str(binary),
                config_path=str(cfg),
                pid_path=str(base / "data/sync/rslsync.pid"),
                log_path=str(base / "data/logs/resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="test-key",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            expected_storage = (base / "data/sync").resolve()
            expected_pid = (expected_storage / "rslsync.pid").resolve()

            def check_storage_prepared() -> bool:
                saved_config = json.loads(cfg.read_text(encoding="utf-8"))
                self.assertEqual(saved_config["storage_path"], str(expected_storage))
                self.assertEqual(saved_config["pid_file"], str(expected_pid))
                self.assertTrue(expected_storage.is_dir())
                self.assertTrue(expected_pid.parent.is_dir())
                self.assertEqual(saved_config["webui"]["api_key"], "test-key")
                return False

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Windows",
                ),
                patch.object(provider, "_cleanup_stale_pid"),
                patch.object(provider, "_is_running", return_value=(False, None)),
                patch.object(provider, "_is_api_reachable", return_value=False),
                patch.object(
                    provider,
                    "_ensure_identity_and_license",
                    side_effect=check_storage_prepared,
                ),
            ):
                status = provider.start()

            self.assertEqual(status.state, "blocked")

    def test_linux_start_sets_child_nofile_to_hard_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / "rslsync"
            binary.write_text("stub", encoding="utf-8")
            cfg = base / "config.json"
            storage = (base / "sync-storage").resolve()
            cfg.write_text(
                f'{{"storage_path":"{storage.as_posix()}"}}', encoding="utf-8"
            )
            key = base / "llng.btskey"
            key.write_text("stub", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path=str(binary),
                config_path=str(cfg),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(key),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch("src.core.sync.resilio_provider.subprocess.run") as mocked_run,
                patch(
                    "src.core.sync.resilio_provider.subprocess.Popen"
                ) as mocked_popen,
                patch("src.core.sync.resilio_provider.resource") as mocked_resource,
                patch.object(provider, "_is_api_reachable", return_value=False),
                patch.object(provider, "metrics", return_value=None),
                patch.object(provider, "_start_process_output_forwarders"),
            ):
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = ""
                mocked_run.return_value.stderr = ""
                mocked_popen.return_value.pid = 2345
                mocked_resource.RLIMIT_NOFILE = 7
                mocked_resource.getrlimit.return_value = (4096, 65535)

                provider.start()

                _args, kwargs = mocked_popen.call_args
                preexec_fn = kwargs.get("preexec_fn")
                self.assertTrue(callable(preexec_fn))
                preexec_fn()

            mocked_resource.getrlimit.assert_called_once_with(7)
            mocked_resource.setrlimit.assert_called_once_with(7, (65535, 65535))
            provider.stop()
            if provider._state.log_handle is not None:  # noqa: SLF001 test cleanup
                provider._state.log_handle.close()  # noqa: SLF001 test cleanup
                provider._state.log_handle = None  # noqa: SLF001 test cleanup

    def test_linux_start_resolves_paths_and_reports_early_exit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            cwd = os.getcwd()
            os.chdir(base)
            try:
                binary = Path("vendor/bin/linux-x64/rslsync")
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_text("stub", encoding="utf-8")
                cfg = Path("config/resilio/config.json")
                cfg.parent.mkdir(parents=True, exist_ok=True)
                cfg.write_text("{}", encoding="utf-8")
                key = Path("vendor/licenses/resilio/llng.btskey")
                key.parent.mkdir(parents=True, exist_ok=True)
                key.write_text("stub", encoding="utf-8")

                provider = ResilioSyncProvider(
                    binary_path=str(binary),
                    config_path=str(cfg),
                    pid_path="data/sync/rslsync.pid",
                    log_path="data/logs/resilio-sync.log",
                    license_key_path=str(key),
                    api_url="http://127.0.0.1:13338/api",
                    api_key="",
                    request_timeout_seconds=0.1,
                    retry_count=1,
                    startup_retry_seconds=0.1,
                )

                with (
                    patch(
                        "src.core.sync.resilio_provider.platform.system",
                        return_value="Linux",
                    ),
                    patch("src.core.sync.resilio_provider.subprocess.run") as mocked_run,
                    patch(
                        "src.core.sync.resilio_provider.subprocess.Popen"
                    ) as mocked_popen,
                    patch.object(provider, "_is_api_reachable", return_value=False),
                    patch.object(provider, "_start_process_output_forwarders"),
                ):
                    mocked_run.return_value.returncode = 0
                    mocked_run.return_value.stdout = ""
                    mocked_run.return_value.stderr = ""
                    mocked_popen.return_value.pid = 4321
                    mocked_popen.return_value.poll.return_value = 1

                    status = provider.start()

                cmd = mocked_popen.call_args.args[0]
                self.assertTrue(Path(cmd[0]).is_absolute())
                self.assertTrue(Path(cmd[2]).is_absolute())
                self.assertFalse(status.running)
                self.assertEqual(status.state, "failed")
                self.assertEqual(status.last_error, "sync_process_exited:1")
            finally:
                os.chdir(cwd)

    def test_linux_start_returns_running_after_bootstrap_changes_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / "rslsync"
            binary.write_text("stub", encoding="utf-8")
            cfg = base / "config.json"
            cfg.write_text("{}", encoding="utf-8")
            key = base / "llng.btskey"
            key.write_text("stub", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path=str(binary),
                config_path=str(cfg),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(key),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch.object(provider, "_cleanup_stale_pid"),
                patch.object(
                    provider,
                    "_ensure_identity_and_license",
                    return_value=True,
                ),
                patch.object(
                    provider,
                    "_is_running",
                    side_effect=[(False, None), (True, 129963), (True, 129963)],
                ),
                patch.object(
                    provider, "_is_api_reachable", side_effect=[False, True]
                ),
                patch("src.core.sync.resilio_provider.subprocess.Popen") as mocked_popen,
            ):
                status = provider.start()

            self.assertTrue(status.running)
            self.assertEqual(status.state, "running")
            self.assertEqual(status.pid, 129963)
            self.assertEqual(mocked_popen.call_count, 0)

    def test_linux_start_treats_pid_lock_as_existing_running_instance(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / "rslsync"
            binary.write_text("stub", encoding="utf-8")
            cfg = base / "config.json"
            cfg.write_text("{}", encoding="utf-8")
            key = base / "llng.btskey"
            key.write_text("stub", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path=str(binary),
                config_path=str(cfg),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(key),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch("src.core.sync.resilio_provider.subprocess.run") as mocked_run,
                patch("src.core.sync.resilio_provider.subprocess.Popen") as mocked_popen,
                patch.object(provider, "_is_api_reachable", return_value=False),
                patch.object(
                    provider,
                    "_is_running",
                    side_effect=[(False, None), (False, None)]
                    + [(True, 129963)] * 10,
                ),
                patch.object(
                    provider,
                    "_startup_log_tail",
                    return_value=[
                        "Can't lock pid file. It seems Resilio Sync is already running with pid 129963"
                    ],
                ),
                patch.object(provider, "_start_process_output_forwarders"),
            ):
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = ""
                mocked_run.return_value.stderr = ""
                mocked_popen.return_value.pid = 4321
                mocked_popen.return_value.poll.return_value = 0

                status = provider.start()

            self.assertFalse(status.running)
            self.assertEqual(status.state, "failed")
            self.assertEqual(status.pid, 4321)
            if provider._state.log_handle is not None:  # noqa: SLF001 test cleanup
                provider._state.log_handle.close()  # noqa: SLF001 test cleanup
                provider._state.log_handle = None  # noqa: SLF001 test cleanup

    def test_linux_start_retries_stale_pid_lock_when_no_instance_appears(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / "rslsync"
            binary.write_text("stub", encoding="utf-8")
            cfg = base / "config.json"
            cfg.write_text("{}", encoding="utf-8")
            key = base / "llng.btskey"
            key.write_text("stub", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path=str(binary),
                config_path=str(cfg),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(key),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            first_proc = Mock()
            first_proc.pid = 4321
            first_proc.poll.return_value = 0
            first_proc.stdout = None
            first_proc.stderr = None
            second_proc = Mock()
            second_proc.pid = 4322
            second_proc.poll.return_value = None
            second_proc.stdout = None
            second_proc.stderr = None

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch("src.core.sync.resilio_provider.subprocess.run") as mocked_run,
                patch("src.core.sync.resilio_provider.subprocess.Popen") as mocked_popen,
                patch.object(provider, "_is_api_reachable", return_value=False),
                patch.object(
                    provider,
                    "_startup_log_tail",
                    return_value=[
                        "Can't lock pid file. It seems Resilio Sync is already running with pid 129963"
                    ],
                ),
                patch.object(provider, "_start_process_output_forwarders"),
                patch.object(provider, "metrics", return_value=None),
            ):
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = ""
                mocked_run.return_value.stderr = ""
                mocked_popen.side_effect = [first_proc, second_proc]

                status = provider.start()

            self.assertTrue(status.running)
            self.assertEqual(status.state, "running")
            self.assertEqual(status.pid, 4322)
            self.assertEqual(mocked_popen.call_count, 2)
            if provider._state.log_handle is not None:  # noqa: SLF001 test cleanup
                provider._state.log_handle.close()  # noqa: SLF001 test cleanup
                provider._state.log_handle = None  # noqa: SLF001 test cleanup

    def test_startup_grace_keeps_status_in_starting_state(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=5.0,
            )
            provider._state.launch_started_at = time.monotonic()  # noqa: SLF001
            with (
                patch.object(provider, "_is_running", return_value=(False, None)),
                patch.object(provider, "_is_api_reachable", return_value=False),
            ):
                status = provider.status()
            self.assertFalse(status.running)
            self.assertEqual(status.state, "starting")

    def test_recovery_rechecks_api_then_restarts_unresponsive_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            failed = SyncStatus(
                provider="resilio",
                running=False,
                state="failed",
                pid=1152,
                last_error="sync_api_unreachable",
            )
            stopped = SyncStatus(provider="resilio", running=False, state="stopped")
            healthy = SyncStatus(provider="resilio", running=True, state="running")
            with (
                patch.object(provider, "status", return_value=failed),
                patch.object(provider, "_startup_grace_active", return_value=False),
                patch.object(provider, "_is_api_reachable", return_value=False) as probe,
                patch.object(provider, "_is_running", return_value=(True, 1152)),
                patch.object(provider, "stop", return_value=stopped) as stop,
                patch.object(provider, "start", return_value=healthy) as start,
                patch("src.core.sync.resilio_provider.time.sleep"),
            ):
                result = provider.recover_if_unhealthy()

            self.assertTrue(result.running)
            self.assertEqual(probe.call_count, 3)
            stop.assert_called_once_with()
            start.assert_called_once_with()

    def test_recovery_aborts_restart_when_api_recovers_during_probes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            failed = SyncStatus(
                provider="resilio", running=False, state="failed", pid=1152
            )
            healthy = SyncStatus(provider="resilio", running=True, state="running")
            with (
                patch.object(provider, "status", side_effect=[failed, healthy]),
                patch.object(provider, "_startup_grace_active", return_value=False),
                patch.object(
                    provider, "_is_api_reachable", side_effect=[False, True]
                ),
                patch.object(provider, "stop") as stop,
                patch.object(provider, "start") as start,
                patch("src.core.sync.resilio_provider.time.sleep"),
            ):
                result = provider.recover_if_unhealthy()

            self.assertTrue(result.running)
            stop.assert_not_called()
            start.assert_not_called()

    def test_process_output_is_mirrored_into_log_file_and_logger(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            log_path = base / "resilio.log"
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(log_path),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            provider._state.log_handle = log_path.open("a", encoding="utf-8")  # noqa: SLF001
            try:
                with self.assertLogs("src.core.sync.resilio_provider", level="INFO") as logs:
                    provider._record_process_output("stdout", "ready to sync")  # noqa: SLF001
                    provider._record_process_output("stderr", "license warning")  # noqa: SLF001
                text = log_path.read_text(encoding="utf-8")
            finally:
                if provider._state.log_handle is not None:  # noqa: SLF001
                    provider._state.log_handle.close()  # noqa: SLF001
                    provider._state.log_handle = None  # noqa: SLF001
            self.assertIn("[stdout] ready to sync", text)
            self.assertIn("[stderr] license warning", text)
            self.assertTrue(
                any("sync_process_stdout=ready to sync" in line for line in logs.output)
            )
            self.assertTrue(
                any("sync_process_stderr=license warning" in line for line in logs.output)
            )

    def test_stop_uses_linux_proc_fallback_when_pid_tracking_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "rslsync"),
                config_path="config/resilio/config.json",
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch.object(provider, "_is_running", return_value=(False, None)),
                patch.object(
                    provider, "_find_configured_process_pid_linux", return_value=7777
                ),
                patch.object(provider, "_is_api_reachable", return_value=False),
                patch("src.core.sync.resilio_provider.os.kill") as mocked_kill,
            ):
                status = provider.stop()
            mocked_kill.assert_called_once_with(7777, 15)
            self.assertFalse(status.running)

    def test_is_running_uses_linux_proc_fallback_when_pid_file_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "rslsync"),
                config_path="config/resilio/config.json",
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch.object(
                    provider, "_find_configured_process_pid_linux", return_value=8123
                ),
            ):
                running, pid = provider._is_running()  # noqa: SLF001
            self.assertTrue(running)
            self.assertEqual(pid, 8123)

    def test_web_ui_url_derives_from_api_url(self) -> None:
        provider = ResilioSyncProvider(
            binary_path="vendor/bin/windows-amd64/btsync.exe",
            config_path="config/resilio.json",
            pid_path="data/sync/rslsync.pid",
            log_path="data/logs/resilio.log",
            license_key_path="vendor/licenses/resilio/llng.btskey",
            api_url="http://127.0.0.1:13338/api",
            api_key="",
            request_timeout_seconds=0.1,
            retry_count=1,
            startup_retry_seconds=0.1,
        )
        self.assertEqual(provider.web_ui_url(), "http://127.0.0.1:13338/gui/")

    def test_identity_and_license_cli_commands_windows(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / "btsync.exe"
            binary.write_text("stub", encoding="utf-8")
            cfg = base / "config.json"
            storage = (base / "sync-storage").resolve()
            cfg.write_text(
                f'{{"storage_path":"{storage.as_posix()}"}}', encoding="utf-8"
            )
            key = base / "llng.btskey"
            key.write_text("stub", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path=str(binary),
                config_path=str(cfg),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(key),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Windows",
                ),
                patch("src.core.sync.resilio_provider.subprocess.run") as mocked_run,
                patch(
                    "src.core.sync.resilio_provider.subprocess.Popen"
                ) as mocked_popen,
                patch.object(provider, "_is_api_reachable", return_value=False),
                patch.object(provider, "metrics", return_value=None),
                patch.object(provider, "_start_process_output_forwarders"),
            ):
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = ""
                mocked_run.return_value.stderr = ""
                mocked_popen.return_value.pid = 1234
                provider.start()
            provider.stop()

            self.assertEqual(
                mocked_run.call_args_list[0].args[0],
                [str(binary), "/config", "config.json", "/identity", "LANLauncher"],
            )
            self.assertEqual(
                mocked_run.call_args_list[1].args[0],
                [str(binary), "/config", "config.json", "/license", str(key.resolve())],
            )
            if provider._state.log_handle is not None:  # noqa: SLF001 test cleanup
                provider._state.log_handle.close()  # noqa: SLF001 test cleanup
                provider._state.log_handle = None  # noqa: SLF001 test cleanup

    def test_identity_and_license_cli_commands_linux_use_runtime_storage_root(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / "rslsync"
            binary.write_text("stub", encoding="utf-8")
            cfg = base / "config" / "resilio" / "config.json"
            cfg.parent.mkdir(parents=True, exist_ok=True)
            cfg.write_text("{}", encoding="utf-8")
            key = base / "llng.btskey"
            key.write_text("stub", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path=str(binary),
                config_path=str(cfg),
                pid_path=str(base / "data" / "sync" / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(key),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch("src.core.sync.resilio_provider.subprocess.run") as mocked_run,
                patch(
                    "src.core.sync.resilio_provider.subprocess.Popen"
                ) as mocked_popen,
                patch.object(provider, "_is_api_reachable", return_value=False),
                patch.object(provider, "metrics", return_value=None),
                patch.object(provider, "_start_process_output_forwarders"),
            ):
                mocked_run.return_value.returncode = 0
                mocked_run.return_value.stdout = ""
                mocked_run.return_value.stderr = ""
                mocked_popen.return_value.pid = 4321
                provider.start()

            runtime_storage = str((base / "data" / "sync").resolve())
            self.assertEqual(
                mocked_run.call_args_list[0].args[0],
                [
                    str(binary),
                    "--storage",
                    runtime_storage,
                    "--identity",
                    "LauncherNG",
                ],
            )
            self.assertEqual(
                mocked_run.call_args_list[1].args[0],
                [
                    str(binary),
                    "--storage",
                    runtime_storage,
                    "--license",
                    str(key.resolve()),
                ],
            )
            if provider._state.log_handle is not None:  # noqa: SLF001 test cleanup
                provider._state.log_handle.close()  # noqa: SLF001 test cleanup
                provider._state.log_handle = None  # noqa: SLF001 test cleanup
            if provider._state.log_handle is not None:  # noqa: SLF001 test cleanup
                provider._state.log_handle.close()  # noqa: SLF001 test cleanup
                provider._state.log_handle = None  # noqa: SLF001 test cleanup

    def test_start_blocked_when_license_activation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            binary = base / "btsync.exe"
            binary.write_text("stub", encoding="utf-8")
            cfg = base / "config.json"
            cfg.write_text("{}", encoding="utf-8")
            key = base / "llng.btskey"
            key.write_text("stub", encoding="utf-8")

            provider = ResilioSyncProvider(
                binary_path=str(binary),
                config_path=str(cfg),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(key),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Windows",
                ),
                patch("src.core.sync.resilio_provider.subprocess.run") as mocked_run,
                patch(
                    "src.core.sync.resilio_provider.subprocess.Popen"
                ) as mocked_popen,
                patch.object(provider, "_is_api_reachable", return_value=False),
            ):
                mocked_run.return_value.returncode = 5
                mocked_run.return_value.stdout = ""
                mocked_run.return_value.stderr = ""
                status = provider.start()

            self.assertFalse(status.running)
            self.assertEqual(status.state, "blocked")
            self.assertEqual(mocked_popen.call_count, 0)

    def test_status_running_when_api_reachable_without_pid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )

            with patch.object(
                provider, "_request_api", return_value={"download": 0, "upload": 0}
            ):
                status = provider.status()

            self.assertTrue(status.running)
            self.assertEqual(status.state, "running")

    def test_folder_sync_status_prefers_download_percent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = {
                "folders": [
                    {
                        "dir": folder.replace("/", "\\"),
                        "download": 100,
                        "progress": 39,
                    }
                ]
            }
            with (
                patch.object(
                    provider, "_request_api_with_params", return_value=payload
                ),
                patch.object(provider, "_request_api", return_value=payload),
            ):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 100)

    def test_folder_sync_status_accepts_top_level_array_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = [
                {
                    "dir": folder.replace("/", "\\"),
                    "size": 1000,
                    "total_size": 1000,
                    "secret": "SECRET-DEMO",
                }
            ]
            with (
                patch.object(
                    provider, "_request_api_with_params", return_value=payload
                ),
                patch.object(provider, "_request_api", return_value=payload),
            ):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 100)

    def test_folder_sync_status_uses_down_diff_and_total_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "aoe3").resolve())
            payload = [
                {
                    "dir": folder.replace("/", "\\"),
                    "down_diff": 2282523694,
                    "size": 670,
                    "total_size": 2603209510,
                }
            ]
            with patch.object(provider, "_request_api", return_value=payload):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 12)

    def test_folder_sync_status_uses_size_and_total_size(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = {
                "folders": [
                    {
                        "dir": folder.replace("/", "\\"),
                        "size": 500,
                        "total_size": 1000,
                        "download": 99,
                    }
                ]
            }
            with patch.object(provider, "_request_api", return_value=payload):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 50)

    def test_folder_sync_status_marks_complete_when_size_equals_total_size(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = {
                "folders": [
                    {"dir": folder.replace("/", "\\"), "size": 2048, "total_size": 2048}
                ]
            }
            with patch.object(provider, "_request_api", return_value=payload):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 100)

    def test_folder_sync_status_fallback_matches_by_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = {
                "folders": [
                    {
                        "dir": str((base / "other-root" / "demo").resolve()).replace(
                            "/", "\\"
                        ),
                        "download": 64,
                    }
                ]
            }
            with patch.object(provider, "_request_api", return_value=payload):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 64)

    def test_folder_sync_status_uses_status_percent_string(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = {
                "folders": [{"dir": folder.replace("/", "\\"), "status": "Syncing 92%"}]
            }
            with patch.object(provider, "_request_api", return_value=payload):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 92)

    def test_folder_sync_status_uses_numeric_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = {"folders": [{"dir": folder.replace("/", "\\"), "status": 87}]}
            with patch.object(provider, "_request_api", return_value=payload):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 87)

    def test_folder_sync_status_includes_activity_metrics(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = {
                "folders": [
                    {"id": "abc", "dir": folder.replace("/", "\\"), "download": 35}
                ]
            }
            with (
                patch.object(provider, "_request_api", return_value=payload),
                patch.object(
                    provider,
                    "_folder_activity",
                    return_value={
                        "down_eta": 321,
                        "down_speed": 2048,
                        "down_status": 1,
                    },
                ),
            ):
                status = provider.folder_sync_status(folder)
            self.assertEqual(status["progress_percent"], 35)
            self.assertEqual(status["down_eta"], 321)
            self.assertEqual(status["down_speed"], 2048)
            self.assertEqual(status["down_status"], 1)

    def test_folder_sync_status_includes_downloaded_and_total_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = {
                "folders": [
                    {
                        "dir": folder.replace("/", "\\"),
                        "size": 104857600,
                        "total_size": 524288000,
                    }
                ]
            }
            with patch.object(provider, "_request_api", return_value=payload):
                status = provider.folder_sync_status(folder)
            self.assertEqual(status["downloaded_bytes"], 104857600)
            self.assertEqual(status["total_bytes"], 524288000)

    def test_folder_sync_status_uses_secret_query_when_cached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            provider._folder_secret_cache[provider._normalize_dir_for_match(folder)] = (
                "SECRET123"  # noqa: SLF001
            )
            payload = {
                "folders": [
                    {"dir": folder.replace("/", "\\"), "size": 10, "total_size": 20}
                ]
            }
            with (
                patch.object(
                    provider, "_request_api_with_params", return_value=payload
                ) as mocked_secret,
                patch.object(provider, "_request_api") as mocked_plain,
            ):
                status = provider.folder_sync_status(folder)

            self.assertEqual(status["progress_percent"], 50)
            self.assertEqual(
                mocked_secret.call_args.args,
                ("get_folders", {"secret": "SECRET123"}),
            )
            self.assertEqual(mocked_secret.call_args.kwargs, {"raw_query": True})
            self.assertFalse(mocked_plain.called)

    def test_existing_folder_secret_fallback_matches_by_folder_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            payload = {
                "folders": [
                    {
                        "dir": str((base / "other-root" / "demo").resolve()).replace(
                            "/", "\\"
                        ),
                        "secret": "SECRET-DEMO",
                    }
                ]
            }
            with patch.object(provider, "_request_api", return_value=payload):
                secret = provider._existing_folder_secret(folder)  # noqa: SLF001
            self.assertEqual(secret, "SECRET-DEMO")

    def test_folder_sync_status_matches_item_by_secret_when_dir_differs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            provider._folder_secret_cache[provider._normalize_dir_for_match(folder)] = (
                "SECRET-DEMO"  # noqa: SLF001
            )
            payload = {
                "folders": [
                    {
                        "dir": str((base / "other-root" / "demo").resolve()).replace(
                            "/", "\\"
                        ),
                        "secret": "SECRET-DEMO",
                        "size": 100,
                        "total_size": 100,
                    }
                ]
            }
            with patch.object(
                provider, "_request_api_with_params", return_value=payload
            ):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 100)

    def test_folder_sync_status_falls_back_when_secret_scoped_call_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "demo").resolve())
            provider._folder_secret_cache[provider._normalize_dir_for_match(folder)] = (
                "SECRET-DEMO"  # noqa: SLF001
            )
            payload = {
                "folders": [
                    {
                        "dir": folder.replace("/", "\\"),
                        "secret": "SECRET-DEMO",
                        "size": 80,
                        "total_size": 100,
                    }
                ]
            }
            with (
                patch.object(
                    provider,
                    "_request_api_with_params",
                    side_effect=RuntimeError("Unsupported API payload format"),
                ),
                patch.object(provider, "_request_api", return_value=payload),
            ):
                status = provider.folder_sync_status(folder)
            self.assertTrue(status["active"])
            self.assertEqual(status["progress_percent"], 80)

    def test_remove_folder_sync_uses_dir_and_secret(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "blobby").resolve())
            with (
                patch.object(
                    provider,
                    "_existing_folder_secret",
                    return_value="B3OYPI5GGCH5SGDRNVFCEIFUO7DLBAT5S",
                ),
                patch.object(
                    provider, "_request_api_raw", return_value={}
                ) as mocked_raw,
            ):
                ok, detail = provider.remove_folder_sync(folder)

            self.assertTrue(ok)
            self.assertEqual(detail, "ok")
            expected_dir = (
                folder.replace("/", "\\")
                if platform.system().lower().startswith("win")
                else folder
            )
            self.assertEqual(
                mocked_raw.call_args_list[0].args,
                (
                    "remove_folder",
                    [
                        ("dir", expected_dir),
                        ("secret", "B3OYPI5GGCH5SGDRNVFCEIFUO7DLBAT5S"),
                    ],
                ),
            )

    def test_ensure_folder_synced_uses_native_linux_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = str((base / "LAN" / "newgame").resolve())
            with (
                patch(
                    "src.core.sync.resilio_provider.platform.system",
                    return_value="Linux",
                ),
                patch.object(provider, "_existing_folder_secret", return_value=""),
                patch.object(
                    provider, "_request_api_raw", return_value={}
                ) as mocked_raw,
            ):
                ok, detail = provider.ensure_folder_synced(folder, "SECRET")
            self.assertTrue(ok)
            self.assertEqual(detail, "ok")
            add_call = mocked_raw.call_args_list[0].args
            self.assertEqual(add_call[0], "add_folder")
            self.assertIn(("dir", folder), add_call[1])

    def test_ensure_folder_synced_creates_missing_folder_before_api_calls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            provider = ResilioSyncProvider(
                binary_path=str(base / "btsync.exe"),
                config_path=str(base / "config.json"),
                pid_path=str(base / "rslsync.pid"),
                log_path=str(base / "resilio.log"),
                license_key_path=str(base / "llng.btskey"),
                api_url="http://127.0.0.1:13338/api",
                api_key="",
                request_timeout_seconds=0.1,
                retry_count=1,
                startup_retry_seconds=0.1,
            )
            folder = base / "LAN" / "newgame"
            self.assertFalse(folder.exists())
            with (
                patch.object(provider, "_existing_folder_secret", return_value=""),
                patch.object(
                    provider, "_request_api_raw", return_value={}
                ) as mocked_raw,
            ):
                ok, detail = provider.ensure_folder_synced(str(folder), "SECRET")
            self.assertTrue(ok)
            self.assertEqual(detail, "ok")
            self.assertTrue(folder.exists())
            self.assertTrue(folder.is_dir())
            self.assertGreaterEqual(mocked_raw.call_count, 1)


if __name__ == "__main__":
    unittest.main()
