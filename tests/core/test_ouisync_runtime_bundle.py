from __future__ import annotations

import asyncio
import hashlib
import json
import platform
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from src.core.tools.bundle_check import run_bundle_checks
from src.core.sync.ouisync_session import ensure_vendor_python_path, load_session_api


class OuisyncRuntimeBundleTests(unittest.TestCase):
    def test_vendor_packages_are_found_from_source_layout(self) -> None:
        vendor_path = ensure_vendor_python_path()

        self.assertTrue((vendor_path / "ouisync" / "session").is_dir())
        self.assertTrue((vendor_path / "msgpack" / "__init__.py").is_file())

    def test_upstream_session_and_msgpack_fallback_import(self) -> None:
        session = load_session_api()
        import msgpack

        self.assertTrue(callable(session.connect))
        self.assertTrue(hasattr(session, "Request_SessionListRepositories"))
        self.assertEqual(msgpack.unpackb(msgpack.packb({"repo": [1, "ok"]})), {"repo": [1, "ok"]})

    def test_cli_bundle_manifest_and_platform_binary(self) -> None:
        root = Path(__file__).resolve().parents[2]
        manifest_path = root / "tools" / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        ouisync_tools = [tool for tool in manifest["tools"] if tool["name"] == "ouisync"]
        self.assertEqual(
            {tool["platform"] for tool in ouisync_tools},
            {"windows-amd64", "linux-x64"},
        )

        platform_tag = "windows-amd64" if platform.system() == "Windows" else "linux-x64"
        tool = next(item for item in ouisync_tools if item["platform"] == platform_tag)
        binary_path = root / tool["path"]
        self.assertEqual(
            hashlib.sha256(binary_path.read_bytes()).hexdigest(), tool["sha256"]
        )

        result = run_bundle_checks(str(manifest_path), repo_root=str(root))
        self.assertTrue(result.ok, result.errors)

        if platform_tag == "linux-x64" or platform.system() == "Windows":
            completed = subprocess.run(
                [str(binary_path), "--version"],
                check=True,
                capture_output=True,
                text=True,
                timeout=15,
            )
            self.assertIn("ouisync 0.10.2", completed.stdout)

    @unittest.skipUnless(platform.system() in {"Linux", "Windows"}, "Ouisync CLI is bundled for Linux and Windows")
    def test_session_binding_connects_to_bundled_cli(self) -> None:
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads((root / "tools" / "manifest.json").read_text(encoding="utf-8"))
        tag = "windows-amd64" if platform.system() == "Windows" else "linux-x64"
        tool = next(
            item
            for item in manifest["tools"]
            if item["name"] == "ouisync" and item["platform"] == tag
        )

        with tempfile.TemporaryDirectory(prefix="llng-ouisync-test-") as temporary:
            config_dir = Path(temporary) / "config"
            config_dir.mkdir()
            process = subprocess.Popen(
                [str(root / tool["path"]), "--config-dir", str(config_dir), "start"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            try:
                endpoint = config_dir / "local_endpoint.conf"
                deadline = time.monotonic() + 20
                while not endpoint.is_file() and time.monotonic() < deadline:
                    if process.poll() is not None:
                        self.fail(f"Ouisync CLI exited during startup: {process.returncode}")
                    time.sleep(0.1)
                self.assertTrue(endpoint.is_file(), "Ouisync CLI did not publish its local endpoint")

                async def connect_and_list() -> dict:
                    session_api = load_session_api()
                    session = await session_api.connect(config_dir)
                    try:
                        return await session.list_repositories()
                    finally:
                        await session_api.close(session)

                self.assertEqual(asyncio.run(connect_and_list()), {})
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
