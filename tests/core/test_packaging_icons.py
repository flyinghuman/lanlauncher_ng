"""Regression checks for packaging icon wiring."""

from __future__ import annotations

import unittest
from pathlib import Path


class PackagingIconTests(unittest.TestCase):
    def test_icon_assets_exist(self) -> None:
        base = Path("src/frontend/assets/icons")
        for name in ("lanlauncherng.svg", "lanlauncherng.png", "lanlauncherng.ico"):
            path = base / name
            self.assertTrue(path.exists(), f"Missing icon asset: {path}")
            self.assertGreater(path.stat().st_size, 0, f"Empty icon asset: {path}")

    def test_windows_inno_uses_custom_icon(self) -> None:
        script = Path("packaging/windows/inno/lanlauncherng.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn("SetupIconFile=", script)
        self.assertIn("IconFilename:", script)
        self.assertIn("lanlauncherng.ico", script)
        self.assertIn('#define MyAppExeName "run.bat"', script)

    def test_windows_packaging_script_uses_console_python(self) -> None:
        script = Path("tools/scripts/package-windows.ps1").read_text(encoding="utf-8")
        self.assertIn("run.bat", script)
        self.assertIn("vendor\\bin\\windows-amd64\\python\\python.exe", script)
        self.assertIn(
            "Run ./.venv-dev-win/Scripts/python.exe tools/scripts/generate-app-icons.py",
            script,
        )
        self.assertIn(
            '$runtimeRoot = Join-Path $root "vendor/bin/windows-amd64/python"',
            script,
        )
        self.assertIn(
            "Assert-NoDeveloperMachineReferences -PackageRoot $out -Needles $leakNeedles",
            script,
        )
        self.assertIn("Do NOT close this window while the launcher is active.", script)
        self.assertNotIn("__minimized__", script)
        self.assertIn("function Update-ToolManifestChecksums", script)
        self.assertIn("function Assert-NoDeveloperMachineReferences", script)
        self.assertIn("function Get-RepositoryRoot", script)
        self.assertIn("function Resolve-OutputPath", script)
        self.assertIn("function Resolve-PowerShellBinary", script)
        self.assertIn(
            'Remove-PythonBuildArtifacts -RootPath (Join-Path $out "vendor/python")',
            script,
        )
        self.assertIn(
            'foreach ($candidate in @("pwsh", "powershell"))', script
        )
        self.assertIn(
            "Update-ToolManifestChecksums -ManifestPath $toolManifestPath -RepoRoot $root",
            script,
        )
        self.assertIn(
            'Copy-Item -Force (Join-Path $root "vendor/licenses/python/LICENSE.txt")',
            script,
        )
        self.assertNotIn(
            'Copy-Item -Force (Join-Path $root "vendor/licenses/resilio/llng.btskey")',
            script,
        )
        self.assertIn(
            'Remove-PythonBuildArtifacts -RootPath (Join-Path $out "app/tools")',
            script,
        )
        self.assertIn('"log_path": "data/logs/log.txt",', script)
        self.assertIn(
            "$out = Resolve-OutputPath -RepoRoot $root -PathValue $OutputRoot",
            script,
        )
        self.assertIn("UTF8Encoding($false)", script)

    def test_windows_installer_script_refreshes_tool_manifest_checksums(self) -> None:
        script = Path("tools/scripts/build-installer-windows.ps1").read_text(
            encoding="utf-8"
        )
        self.assertIn("function Get-RepositoryRoot", script)
        self.assertIn("function Resolve-RepoPath", script)
        self.assertIn("function Convert-ToWinePath", script)
        self.assertIn("Get-Command winepath -ErrorAction SilentlyContinue", script)
        self.assertIn(
            "$winePackageRoot = Convert-ToWinePath -PathValue $resolvedPackageRoot",
            script,
        )
        self.assertIn(
            "$wineInnoScript = Convert-ToWinePath -PathValue $resolvedInnoScript",
            script,
        )
        self.assertIn("function Update-ToolManifestChecksums", script)
        self.assertIn("if ($SkipPackageBuild)", script)
        self.assertIn(
            '$runtimePython = Join-Path $repoRoot "vendor/bin/windows-amd64/python/python.exe"',
            script,
        )
        self.assertIn("function Resolve-PowerShellBinary", script)
        self.assertIn(
            'foreach ($candidate in @("pwsh", "powershell"))', script
        )
        self.assertIn(
            "& $powerShellExe -ExecutionPolicy Bypass -File $runtimeBuilder",
            script,
        )
        self.assertIn(
            "$homeDir = if ([string]::IsNullOrWhiteSpace($env:HOME)) {", script
        )
        self.assertIn(
            ".wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe",
            script,
        )
        self.assertIn('$normalizedIsccPath = $iscc -replace "\\\\", "/"', script)
        self.assertIn(
            '$isWineIscc = $normalizedIsccPath -like "*/.wine/*"',
            script,
        )
        self.assertNotIn(
            '$isWineIscc = $IsLinux -and ($iscc -like "*/.wine/*")',
            script,
        )
        self.assertIn("Get-Command wine -ErrorAction SilentlyContinue", script)
        self.assertIn(
            "Update-ToolManifestChecksums -ManifestPath $packagedManifest -BaseRoot $resolvedPackageRoot",
            script,
        )
        self.assertIn(
            'Update-ToolManifestChecksums -ManifestPath (Join-Path $repoRoot "tools/manifest.json") -BaseRoot $repoRoot',
            script,
        )
        self.assertIn("UTF8Encoding($false)", script)
        inno = Path("packaging/windows/inno/lanlauncherng.iss").read_text(
            encoding="utf-8"
        )
        self.assertIn("procedure CopyOptionalInstallerAsset", inno)
        self.assertIn("CurStepChanged(CurStep: TSetupStep)", inno)
        self.assertIn("ExpandConstant('{srcexe}')", inno)
        self.assertIn("btsync.exe", inno)
        self.assertIn("llng.btskey", inno)
        self.assertIn("bootstrap.json", inno)
        self.assertIn("{app}\\vendor\\bin\\windows-amd64\\btsync.exe", inno)
        self.assertIn("{app}\\config\\optional-bootstrap.json", inno)

        for readme_name in ("README.md", "README.txt"):
            readme = Path("packaging/windows") / readme_name
            self.assertTrue(readme.is_file(), f"Missing Windows installer guide: {readme}")
        self.assertIn('"README.md", "README.txt"', script)
        self.assertIn('Join-Path $repoRoot "ng_provider/bootstrap.json"', script)
        self.assertIn('Join-Path $installerOutputDir "bootstrap.json"', script)

    def test_installer_guides_and_bootstrap_template_ship_with_linux_archive(self) -> None:
        build_script = Path("tools/scripts/build-installer-linux.sh").read_text(
            encoding="utf-8"
        )
        for readme_name in ("README.md", "README.txt"):
            readme = Path("packaging/linux") / readme_name
            self.assertTrue(readme.is_file(), f"Missing Linux installer guide: {readme}")
            self.assertIn(f'"packaging/linux/{readme_name}"', build_script)
        self.assertIn('if [[ -f "ng_provider/bootstrap.json" ]]', build_script)
        self.assertIn('"ng_provider/bootstrap.json"', build_script)

    def test_provider_readmes_explain_optional_resilio_sidecars(self) -> None:
        windows = Path("packaging/windows/README.md").read_text(encoding="utf-8")
        linux = Path("packaging/linux/README.md").read_text(encoding="utf-8")
        for text in (windows, linux):
            self.assertIn("game_provider_type", text)
            self.assertIn("bootstrap.json", text)
            self.assertIn("llng.btskey", text)
            self.assertIn("Terms of Use", text)
        self.assertIn("btsync.exe", windows)
        self.assertIn("rslsync", linux)

    def test_tool_manifest_excludes_resilio_binaries(self) -> None:
        manifest = Path("tools/manifest.json").read_text(encoding="utf-8")
        self.assertNotIn("vendor/bin/windows-amd64/btsync.exe", manifest)
        self.assertNotIn("vendor/bin/linux-x64/rslsync", manifest)
        self.assertNotIn("vendor/licenses/resilio/llng.btskey", manifest)
        self.assertNotIn("vendor/bin/windows-amd64/syncthing.exe", manifest)
        self.assertNotIn("vendor/bin/linux-x64/syncthing", manifest)

    def test_cross_platform_release_wrapper_calls_existing_builders(self) -> None:
        script = Path(
            "tools/scripts/build-cross-platform-installer-and-updater.sh"
        ).read_text(encoding="utf-8")
        self.assertIn("set -euo pipefail", script)
        self.assertIn(
            "tools/scripts/build-installer-and-update-windows.ps1",
            script,
        )
        self.assertIn("tools/scripts/build-installer-linux.sh", script)
        self.assertIn("tools/scripts/build_update_package.py", script)
        self.assertIn("dist/windows/lanlauncherng", script)
        self.assertIn("dist/windows/update", script)
        self.assertIn("dist/linux/lanlauncherng", script)
        self.assertIn("dist/linux/installer", script)
        self.assertIn("dist/linux/update", script)
        self.assertIn("secrets/llng-update-private.pem", script)
        self.assertIn("secrets/llng-update-public.pem", script)

    def test_linux_desktop_entry_uses_icon(self) -> None:
        install = Path("packaging/linux/install.sh").read_text(encoding="utf-8")
        uninstall = Path("packaging/linux/uninstall.sh").read_text(encoding="utf-8")
        self.assertIn("/usr/share/pixmaps/lanlauncherng.png", install)
        self.assertIn("Icon=lanlauncherng", install)
        self.assertIn("/usr/share/pixmaps/lanlauncherng.png", uninstall)
        self.assertIn('DESKTOP_SHORTCUT_NAME="LANLauncherNG.desktop"', install)
        self.assertIn('ROOT_DESKTOP_DIR="/root/Desktop"', install)
        self.assertIn('write_desktop_entry "$DESKTOP_FILE"', install)
        self.assertIn('write_desktop_entry "$ROOT_DESKTOP_FILE"', install)
        self.assertIn(
            'USER_DESKTOP_FILE="$USER_DESKTOP_DIR/$DESKTOP_SHORTCUT_NAME"', install
        )
        self.assertIn(
            'chown "$SUDO_USER":"$SUDO_USER" "$USER_DESKTOP_FILE" || true', install
        )
        self.assertIn(
            'ROOT_DESKTOP_FILE="/root/Desktop/$DESKTOP_SHORTCUT_NAME"', uninstall
        )
        self.assertIn('rm -f "$ROOT_DESKTOP_FILE"', uninstall)
        self.assertIn('rm -f "$SUDO_HOME/Desktop/$DESKTOP_SHORTCUT_NAME"', uninstall)
        self.assertIn('SYSTEM_PYTHON_BIN="${SYSTEM_PYTHON_BIN:-python3}"', install)
        self.assertIn('rm -rf "$PREFIX/.venv-runtime-lin"', install)
        self.assertIn(
            '"$SYSTEM_PYTHON_BIN" -m venv --without-pip --copies "$PREFIX/.venv-runtime-lin"',
            install,
        )
        self.assertIn(
            'if [[ ! -x "$PREFIX/.venv-runtime-lin/bin/python" ]]; then',
            install,
        )
        self.assertIn('APP_OWNER_GROUP="$(id -gn "$SUDO_USER"', install)
        self.assertIn("for rel in data config; do", install)
        self.assertIn(
            'chown -R "$SUDO_USER":"$APP_OWNER_GROUP" "$target" || true', install
        )
        self.assertIn('chmod -R u+rwX "$target" || true', install)
        self.assertIn("copy_optional_asset()", install)
        self.assertIn(
            'copy_optional_asset "rslsync" "vendor/bin/linux-x64/rslsync"',
            install,
        )
        self.assertIn("warn_if_missing_resilio_binary()", install)
        self.assertIn(
            "Warning: Resilio mode needs a local rslsync binary; place rslsync next to install.sh before installing if you plan to use Resilio.",
            install,
        )
        self.assertIn(
            "Warnung: Der Resilio-Modus benötigt ein lokales rslsync-Binärprogramm; lege rslsync vor der Installation neben install.sh, wenn du Resilio verwenden möchtest.",
            install,
        )
        self.assertNotIn('copy_optional_asset "syncthing"', install)
        self.assertIn(
            'copy_optional_asset "llng.btskey" "vendor/licenses/resilio/llng.btskey"',
            install,
        )
        self.assertIn(
            'copy_optional_asset "bootstrap.json" "config/optional-bootstrap.json"',
            install,
        )

    def test_linux_package_script_rebuilds_invalid_runtime_venv(self) -> None:
        script = Path("packaging/linux/package-linux.sh").read_text(encoding="utf-8")
        self.assertIn("\"$OUT/vendor/python\" -type d -name '__pycache__'", script)
        self.assertIn("-name '__pycache__' -prune -exec rm -rf {} +", script)
        self.assertIn('"log_path": "data/logs/log.txt",', script)
        self.assertIn('if [[ ! -x "$RUNTIME_VENV/bin/python" ]]; then', script)
        self.assertIn('RUNTIME_VENV="$ROOT/.venv-runtime-lin"', script)
        self.assertIn('echo "Building runtime venv at $RUNTIME_VENV ..."', script)
        self.assertIn('if compgen -G "vendor/bin/linux-x64/*" > /dev/null; then', script)
        self.assertNotIn('cp "vendor/licenses/resilio/llng.btskey"', script)
        self.assertIn('SCRIPT_SOURCE="${BASH_SOURCE[0]}"', script)
        self.assertIn('while [[ -h "$SCRIPT_SOURCE" ]]; do', script)
        self.assertIn('SCRIPT_SOURCE="$(readlink "$SCRIPT_SOURCE")"', script)
        self.assertIn('if [[ ! -f ".venv-runtime-lin/bin/python" ]]; then', script)
        self.assertIn('if [[ ! -x ".venv-runtime-lin/bin/python" ]]; then', script)

    def test_runtime_venv_builder_uses_copies(self) -> None:
        script = Path("tools/scripts/build-runtime-venv.sh").read_text(encoding="utf-8")
        self.assertIn('VENV_PATH="${1:-.venv-runtime-lin}"', script)
        self.assertIn("-m venv --without-pip --copies", script)
        self.assertIn('if [[ ! -x "$VENV_PATH/bin/python" ]]; then', script)

    def test_windows_dev_venv_builder_and_test_runner_use_dev_env(self) -> None:
        build_script = Path("tools/scripts/build-dev-venv-win.ps1").read_text(
            encoding="utf-8"
        )
        test_script = Path("tools/scripts/run-tests.ps1").read_text(encoding="utf-8")
        runtime_builder = Path("tools/scripts/build-runtime-venv.ps1").read_text(
            encoding="utf-8"
        )
        runtime_updater = Path(
            "tools/scripts/update-bundled-python-runtime.ps1"
        ).read_text(encoding="utf-8")
        installer_update = Path(
            "tools/scripts/build-installer-and-update-windows.ps1"
        ).read_text(encoding="utf-8")
        self.assertIn('[string]$VenvPath = ".venv-dev-win"', build_script)
        self.assertIn(
            '[string]$RequirementsPath = "requirements-dev-win.txt"', build_script
        )
        self.assertIn(
            '$python = ".\\\\.venv-dev-win\\\\Scripts\\\\python.exe"',
            test_script,
        )
        self.assertIn(
            "Python virtual environment not found at .venv-dev-win.", test_script
        )
        self.assertIn(
            '[string]$RuntimePath = "vendor/bin/windows-amd64/python"',
            runtime_builder,
        )
        self.assertIn(
            '[string]$PythonVersion = "3.14.0"',
            runtime_builder,
        )
        self.assertIn(
            "https://www.python.org/ftp/python/$PythonVersion/$archiveName",
            runtime_builder,
        )
        self.assertIn(
            "Write-PthFile -RuntimeRoot $runtimeRoot -RuntimeTag $pythonTag",
            runtime_builder,
        )
        self.assertIn(
            'Copy-Item -Force $licenseSource (Join-Path $licenseRoot "LICENSE.txt")',
            runtime_builder,
        )
        self.assertIn("[switch]$LatestStable", runtime_updater)
        self.assertIn(
            '[string]$ManifestPath = "tools/manifest.json"',
            runtime_updater,
        )
        self.assertIn(
            '$indexUrl = "https://www.python.org/ftp/python/"',
            runtime_updater,
        )
        self.assertIn(
            '$_ .platform -eq "windows-amd64"',
            runtime_updater.replace("$_.platform", "$_ .platform"),
        )
        self.assertIn(
            "& powershell -ExecutionPolicy Bypass -File $resolvedBuilder -PythonVersion $targetVersion",
            runtime_updater,
        )
        self.assertIn(
            "$entry.sha256 = (Get-FileHash -Path $runtimeExe -Algorithm SHA256).Hash.ToLowerInvariant()",
            runtime_updater,
        )
        self.assertIn(
            '$vendorPython = Join-Path $RepoRoot "vendor/bin/windows-amd64/python/python.exe"',
            installer_update,
        )
        self.assertNotIn(".venv/bin/python", installer_update)
        self.assertNotIn(".venv-dev-win/Scripts/python.exe", installer_update)
        self.assertIn("function Resolve-PowerShellBinary", installer_update)
        self.assertIn(
            'foreach ($candidate in @("pwsh", "powershell"))', installer_update
        )

    def test_linux_installer_builder_excludes_runtime_venv_payload(self) -> None:
        script = Path("tools/scripts/build-installer-linux.sh").read_text(
            encoding="utf-8"
        )
        self.assertIn('cp -a "$PACKAGE_ROOT" "$STAGING_DIR/lanlauncherng"', script)
        self.assertIn('rm -rf "$STAGING_DIR/lanlauncherng/.venv-runtime-lin"', script)


if __name__ == "__main__":
    unittest.main()
