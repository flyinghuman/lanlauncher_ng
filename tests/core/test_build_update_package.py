"""Tests for update package build helper script."""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from zipfile import ZipFile


def _load_builder_module():
    script_path = Path("tools/scripts/build_update_package.py").resolve()
    spec = importlib.util.spec_from_file_location("build_update_package", script_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load script module: {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[attr-defined]
    return module


class BuildUpdatePackageTests(unittest.TestCase):
    def test_install_builders_do_not_copy_publisher_folder(self) -> None:
        linux_builder = Path("packaging/linux/package-linux.sh").read_text(
            encoding="utf-8"
        )
        windows_builder = Path("tools/scripts/package-windows.ps1").read_text(
            encoding="utf-8"
        )
        self.assertNotIn('cp -R "$ROOT/ng_provider"', linux_builder)
        self.assertNotIn(
            'Copy-Item -Recurse -Force (Join-Path $root "ng_provider")',
            windows_builder,
        )

    def test_update_payload_excludes_ng_provider_publisher_files(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package_root = root / "package"
            staging_parent = root / "staging"
            (package_root / "app").mkdir(parents=True)
            (package_root / "app" / "launcher.py").write_text("app", encoding="utf-8")
            (package_root / "ng_provider").mkdir()
            (package_root / "ng_provider" / "Dockerfile").write_text(
                "publisher tooling", encoding="utf-8"
            )
            (package_root / "ng_provider" / ".env").write_text(
                "vpn credentials", encoding="utf-8"
            )
            staging_parent.mkdir()

            with patch.object(
                module.tempfile, "mkdtemp", return_value=str(staging_parent)
            ):
                staged = module._prepare_cross_platform_payload(package_root, "linux")

            self.assertTrue((staged / "app" / "launcher.py").is_file())
            self.assertFalse((staged / "ng_provider").exists())

    def test_unsigned_build_creates_zip_and_manifest(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package_root = tmp_path / "package"
            output_dir = tmp_path / "out"
            (package_root / "app").mkdir(parents=True, exist_ok=True)
            (package_root / "app" / "demo.txt").write_text("hello", encoding="utf-8")

            args = module.parse_args(
                [
                    "--package-root",
                    str(package_root),
                    "--output-dir",
                    str(output_dir),
                    "--version",
                    "1.2.3",
                    "--skip-package-build",
                    "--unsigned",
                    "--overwrite",
                ]
            )
            payload_path, manifest_path = module.build_update_package(args)

            self.assertTrue(payload_path.exists())
            self.assertTrue(manifest_path.exists())

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(manifest["version"], "1.2.3")
            self.assertEqual(manifest["payload"]["path"], payload_path.name)
            self.assertEqual(manifest["install"]["mode"], "directory_swap")
            expected_preserve_paths = (
                [
                    "data",
                    "vendor/bin/windows-amd64/btsync.exe",
                    "vendor/licenses/resilio/llng.btskey",
                ]
                if os.name == "nt"
                else [
                    "data",
                    ".venv-runtime-lin",
                    "vendor/bin/linux-x64/rslsync",
                    "vendor/licenses/resilio/llng.btskey",
                ]
            )
            self.assertEqual(
                manifest["install"]["preserve_paths"],
                expected_preserve_paths,
            )
            self.assertNotIn("signature", manifest)

            expected_sha = hashlib.sha256(payload_path.read_bytes()).hexdigest()
            self.assertEqual(manifest["payload"]["sha256"], expected_sha)

    def test_parse_args_rejects_file_exists_without_path(self) -> None:
        module = _load_builder_module()
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                module.parse_args(
                    [
                        "--package-root",
                        "dummy",
                        "--health-check-type",
                        "file_exists",
                        "--skip-package-build",
                        "--unsigned",
                    ]
                )

    def test_replace_or_insert_key_entry_inserts_new_key(self) -> None:
        module = _load_builder_module()
        block = '{\n    "existing": (\n        123,\n        65537,\n    ),\n}\n'
        updated = module._replace_or_insert_key_entry(  # noqa: SLF001
            block, "llng-root-2099", 999, 3
        )
        self.assertIn('"llng-root-2099": (', updated)
        self.assertIn("999", updated)
        self.assertIn("3", updated)

    def test_replace_or_insert_key_entry_replaces_existing_key(self) -> None:
        module = _load_builder_module()
        block = '{\n    "llng-root-2026": (\n        1,\n        65537,\n    ),\n}\n'
        updated = module._replace_or_insert_key_entry(  # noqa: SLF001
            block, "llng-root-2026", 777, 17
        )
        self.assertIn("777", updated)
        self.assertIn("17", updated)
        self.assertNotIn("\n        1,\n", updated)

    def test_resolve_openssl_bin_accepts_explicit_existing_path(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp) / "openssl.exe"
            fake.write_text("x", encoding="utf-8")
            resolved = module._resolve_openssl_bin(str(fake), required=True)  # noqa: SLF001
            self.assertEqual(Path(resolved), fake)

    def test_resolve_openssl_bin_raises_when_required_and_missing(self) -> None:
        module = _load_builder_module()
        with (
            patch("shutil.which", return_value=None),
            patch("pathlib.Path.exists", return_value=False),
        ):
            with self.assertRaises(FileNotFoundError):
                module._resolve_openssl_bin("openssl", required=True)  # noqa: SLF001

    def test_build_update_package_invokes_package_builder_by_default(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package_root = tmp_path / "package"
            output_dir = tmp_path / "out"
            (package_root / "app").mkdir(parents=True, exist_ok=True)
            (package_root / "app" / "demo.txt").write_text("hello", encoding="utf-8")
            package_script = tmp_path / "package-windows.ps1"
            package_script.write_text("# mock", encoding="utf-8")

            args = module.parse_args(
                [
                    "--package-root",
                    str(package_root),
                    "--package-script",
                    str(package_script),
                    "--package-platform",
                    "windows",
                    "--output-dir",
                    str(output_dir),
                    "--version",
                    "1.2.3",
                    "--unsigned",
                    "--overwrite",
                ]
            )
            with patch.object(module, "_build_windows_package") as mock_builder:
                module.build_update_package(args)
                mock_builder.assert_called_once_with(
                    package_script.resolve(), package_root.resolve()
                )

    def test_build_update_package_auto_platform_linux_uses_linux_builder(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package_root = tmp_path / "dist" / "linux" / "lanlauncherng"
            output_dir = tmp_path / "out"
            package_script = tmp_path / "package-linux.sh"
            package_script.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            (package_root / "app").mkdir(parents=True, exist_ok=True)
            (package_root / "app" / "demo.txt").write_text("hello", encoding="utf-8")

            args = module.parse_args(
                [
                    "--package-root",
                    str(package_root),
                    "--package-script",
                    str(package_script),
                    "--output-dir",
                    str(output_dir),
                    "--version",
                    "1.2.3",
                    "--unsigned",
                    "--overwrite",
                ]
            )
            with (
                patch.object(module, "_build_linux_package") as linux_builder,
                patch.object(module, "_build_windows_package") as windows_builder,
            ):
                module.build_update_package(args)
                linux_builder.assert_called_once_with(
                    package_script.resolve(), package_root.resolve()
                )
                windows_builder.assert_not_called()

    def test_linux_update_payload_excludes_runtime_venv_and_preserves_target_one(
        self,
    ) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package_root = tmp_path / "dist" / "linux" / "lanlauncherng"
            output_dir = tmp_path / "out"
            (package_root / "app").mkdir(parents=True, exist_ok=True)
            (package_root / "app" / "demo.txt").write_text("hello", encoding="utf-8")
            (package_root / ".venv-runtime-lin" / "bin").mkdir(
                parents=True, exist_ok=True
            )
            (package_root / ".venv-runtime-lin" / "bin" / "python").write_text(
                "dev-python",
                encoding="utf-8",
            )

            args = module.parse_args(
                [
                    "--package-root",
                    str(package_root),
                    "--package-platform",
                    "linux",
                    "--output-dir",
                    str(output_dir),
                    "--version",
                    "1.2.3",
                    "--skip-package-build",
                    "--unsigned",
                    "--overwrite",
                ]
            )
            payload_path, manifest_path = module.build_update_package(args)

            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["install"]["preserve_paths"],
                [
                    "data",
                    ".venv-runtime-lin",
                    "vendor/bin/linux-x64/rslsync",
                    "vendor/licenses/resilio/llng.btskey",
                ],
            )
            with ZipFile(payload_path, "r") as archive:
                entries = set(archive.namelist())
            self.assertFalse(
                any(name.startswith(".venv-runtime-lin/") for name in entries)
            )

    def test_windows_preserve_paths_keep_local_resilio_assets(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package_root = tmp_path / "package"
            output_dir = tmp_path / "out"
            (package_root / "app").mkdir(parents=True, exist_ok=True)
            (package_root / "app" / "demo.txt").write_text("hello", encoding="utf-8")

            args = module.parse_args(
                [
                    "--package-root",
                    str(package_root),
                    "--package-platform",
                    "windows",
                    "--output-dir",
                    str(output_dir),
                    "--version",
                    "1.2.3",
                    "--skip-package-build",
                    "--unsigned",
                    "--overwrite",
                ]
            )
            _, manifest_path = module.build_update_package(args)
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                manifest["install"]["preserve_paths"],
                [
                    "data",
                    "vendor/bin/windows-amd64/btsync.exe",
                    "vendor/licenses/resilio/llng.btskey",
                ],
            )

    def test_build_update_package_payload_contains_both_run_scripts(self) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package_root = tmp_path / "package"
            output_dir = tmp_path / "out"
            (package_root / "app").mkdir(parents=True, exist_ok=True)
            (package_root / "app" / "demo.txt").write_text("hello", encoding="utf-8")

            args = module.parse_args(
                [
                    "--package-root",
                    str(package_root),
                    "--output-dir",
                    str(output_dir),
                    "--version",
                    "1.2.3",
                    "--skip-package-build",
                    "--unsigned",
                    "--overwrite",
                ]
            )
            payload_path, _ = module.build_update_package(args)
            with ZipFile(payload_path, "r") as archive:
                entries = set(archive.namelist())
                run_sh = archive.read("run.sh").decode("utf-8")
                run_bat = archive.read("run.bat").decode("utf-8")
            self.assertIn("run.sh", entries)
            self.assertIn("run.bat", entries)
            self.assertIn(".venv-runtime-lin/bin/python", run_sh)
            self.assertIn("vendor\\bin\\windows-amd64\\python\\python.exe", run_bat)

    def test_build_update_package_payload_contains_windows_vendor_bin_folder(
        self,
    ) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            package_root = tmp_path / "package"
            output_dir = tmp_path / "out"
            (package_root / "app").mkdir(parents=True, exist_ok=True)
            (package_root / "app" / "demo.txt").write_text("hello", encoding="utf-8")

            args = module.parse_args(
                [
                    "--package-root",
                    str(package_root),
                    "--output-dir",
                    str(output_dir),
                    "--version",
                    "1.2.3",
                    "--skip-package-build",
                    "--unsigned",
                    "--overwrite",
                ]
            )
            payload_path, _ = module.build_update_package(args)
            with ZipFile(payload_path, "r") as archive:
                entries = set(archive.namelist())
            self.assertTrue(
                any(name.startswith("vendor/bin/windows-amd64/") for name in entries)
            )
            self.assertTrue(
                any(name.startswith("vendor/bin/linux-x64/") for name in entries)
            )

    def test_build_linux_package_uses_repo_relative_output_arg_when_possible(
        self,
    ) -> None:
        module = _load_builder_module()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script_path = tmp_path / "package-linux.sh"
            script_path.write_text("#!/usr/bin/env bash\n", encoding="utf-8")
            package_root = Path.cwd() / "dist" / "linux" / "lanlauncherng"
            package_root.mkdir(parents=True, exist_ok=True)

            class _Completed:
                returncode = 0
                stdout = ""
                stderr = ""

            with patch("subprocess.run", return_value=_Completed()) as run_mock:
                module._build_linux_package(script_path, package_root)  # noqa: SLF001
                args = run_mock.call_args[0][0]
                self.assertEqual(args[0], "bash")
                self.assertEqual(args[1], str(script_path))
                self.assertEqual(args[2], "dist/linux/lanlauncherng")


if __name__ == "__main__":
    unittest.main()
