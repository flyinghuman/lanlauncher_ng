"""Build signed update payload and update-manifest.json for LANLauncherNG."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _sha256_for_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _zip_directory(source_dir: Path, target_zip: Path) -> None:
    if target_zip.exists():
        target_zip.unlink()
    with ZipFile(target_zip, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_dir():
                continue
            arcname = path.relative_to(source_dir).as_posix()
            archive.write(path, arcname)


def _copy_tree_contents(source_dir: Path, target_dir: Path) -> None:
    if not source_dir.exists() or not source_dir.is_dir():
        return
    target_dir.mkdir(parents=True, exist_ok=True)
    for path in sorted(source_dir.rglob("*")):
        if path.is_dir():
            continue
        relative = path.relative_to(source_dir)
        destination = target_dir / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)


def _write_run_sh(path: Path) -> None:
    path.write_text(
        "#!/usr/bin/env bash\n"
        "set -euo pipefail\n"
        'SCRIPT_SOURCE="${BASH_SOURCE[0]}"\n'
        'while [[ -h "$SCRIPT_SOURCE" ]]; do\n'
        '  SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_SOURCE")" && pwd)"\n'
        '  SCRIPT_SOURCE="$(readlink "$SCRIPT_SOURCE")"\n'
        '  [[ "$SCRIPT_SOURCE" != /* ]] && SCRIPT_SOURCE="$SCRIPT_DIR/$SCRIPT_SOURCE"\n'
        "done\n"
        'SCRIPT_DIR="$(cd -P "$(dirname "$SCRIPT_SOURCE")" && pwd)"\n'
        'cd "$SCRIPT_DIR"\n'
        'if [[ ! -f ".venv-runtime-lin/bin/python" ]]; then\n'
        '  echo "Missing bundled Python environment (.venv-runtime-lin)."\n'
        "  exit 1\n"
        "fi\n"
        'if [[ ! -x ".venv-runtime-lin/bin/python" ]]; then\n'
        '  echo "Bundled Python exists but is not executable (.venv-runtime-lin/bin/python)." >&2\n'
        "  exit 1\n"
        "fi\n"
        'export PYTHONPATH="app"\n'
        ".venv-runtime-lin/bin/python -m src.core.main --config config/core.json\n",
        encoding="utf-8",
    )
    path.chmod(path.stat().st_mode | 0o111)


def _write_run_bat(path: Path) -> None:
    path.write_text(
        "@echo off\r\n"
        "setlocal\r\n"
        "cd /d %~dp0\r\n"
        'if not exist ".\\vendor\\bin\\windows-amd64\\python\\python.exe" (\r\n'
        "  echo Missing bundled Python runtime: vendor\\bin\\windows-amd64\\python\\python.exe\r\n"
        "  exit /b 1\r\n"
        ")\r\n"
        'set "PY_EXE=.\\vendor\\bin\\windows-amd64\\python\\python.exe"\r\n'
        '"%PY_EXE%" -m src.core.main --config config\\core.json\r\n',
        encoding="utf-8",
    )


def _prepare_cross_platform_payload(package_root: Path, package_platform: str) -> Path:
    repo_root = _repo_root()
    staging_parent = Path(tempfile.mkdtemp(prefix="llng-update-payload-"))
    staged_root = staging_parent / "package"
    shutil.copytree(package_root, staged_root)
    # ng_provider is publisher data and may contain deployment tooling or secrets.
    shutil.rmtree(staged_root / "ng_provider", ignore_errors=True)

    if package_platform == "linux":
        # Linux target hosts create their runtime venv locally during install, so the
        # update payload must not ship the builder machine's .venv-runtime-lin.
        shutil.rmtree(staged_root / ".venv-runtime-lin", ignore_errors=True)

    # Ensure update payload can start on both OS families.
    run_sh = staged_root / "run.sh"
    run_bat = staged_root / "run.bat"
    if not run_sh.exists():
        _write_run_sh(run_sh)
    if not run_bat.exists():
        _write_run_bat(run_bat)

    vendor_root = staged_root / "vendor" / "bin"
    _copy_tree_contents(
        repo_root / "vendor" / "bin" / "linux-x64", vendor_root / "linux-x64"
    )
    _copy_tree_contents(
        repo_root / "vendor" / "bin" / "windows-amd64", vendor_root / "windows-amd64"
    )
    return staged_root


def _normalize_preserve_paths(
    raw_preserve_paths: list[str], package_platform: str
) -> list[str]:
    cleaned: list[str] = []
    for item in raw_preserve_paths:
        text = str(item or "").strip().replace("\\", "/")
        if not text or text in cleaned:
            continue
        cleaned.append(text)
    if package_platform == "linux" and ".venv-runtime-lin" not in cleaned:
        cleaned.append(".venv-runtime-lin")
    default_local_assets = {
        "linux": [
            "vendor/bin/linux-x64/rslsync",
            "vendor/licenses/resilio/llng.btskey",
        ],
        "windows": [
            "vendor/bin/windows-amd64/btsync.exe",
            "vendor/licenses/resilio/llng.btskey",
        ],
    }
    for item in default_local_assets.get(package_platform, []):
        if item not in cleaned:
            cleaned.append(item)
    return cleaned


def _canonical_manifest_bytes(payload: dict) -> bytes:
    unsigned_payload = {
        key: value for key, value in payload.items() if key != "signature"
    }
    return json.dumps(
        unsigned_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _sign_with_openssl(
    canonical_bytes: bytes, private_key: Path, openssl_bin: str
) -> str:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        canonical_path = tmp_dir / "manifest.bin"
        signature_path = tmp_dir / "signature.bin"
        canonical_path.write_bytes(canonical_bytes)
        cmd = [
            openssl_bin,
            "dgst",
            "-sha256",
            "-sign",
            str(private_key),
            "-out",
            str(signature_path),
            str(canonical_path),
        ]
        completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if completed.returncode != 0:
            stderr = (completed.stderr or "").strip()
            raise RuntimeError(
                f"openssl signing failed ({completed.returncode}): {stderr}"
            )
        signature_raw = signature_path.read_bytes()
        return base64.b64encode(signature_raw).decode("ascii")


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )


def _resolve_powershell_bin() -> str:
    for candidate in ("powershell", "pwsh"):
        resolved = shutil.which(candidate)
        if resolved:
            return resolved
    raise FileNotFoundError("PowerShell executable not found (powershell/pwsh).")


def _build_windows_package(package_script: Path, package_root: Path) -> None:
    if not package_script.exists() or not package_script.is_file():
        raise FileNotFoundError(f"Package builder script not found: {package_script}")
    ps_bin = _resolve_powershell_bin()
    cmd = [
        ps_bin,
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(package_script),
        "-OutputRoot",
        str(package_root),
    ]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout
        raise RuntimeError(
            f"package build failed ({completed.returncode}) via {package_script}: {detail}"
        )


def _build_linux_package(package_script: Path, package_root: Path) -> None:
    if not package_script.exists() or not package_script.is_file():
        raise FileNotFoundError(f"Package builder script not found: {package_script}")
    repo_root = _repo_root().resolve()
    package_arg = str(package_root)
    try:
        package_arg = package_root.resolve().relative_to(repo_root).as_posix()
    except ValueError:
        package_arg = str(package_root)
    cmd = ["bash", str(package_script), package_arg]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        stdout = (completed.stdout or "").strip()
        detail = stderr or stdout
        raise RuntimeError(
            f"package build failed ({completed.returncode}) via {package_script}: {detail}"
        )


def _resolve_package_platform(raw_platform: str, package_root: Path) -> str:
    normalized = str(raw_platform or "").strip().lower()
    if normalized in {"windows", "linux"}:
        return normalized
    lower_path = package_root.as_posix().lower()
    if "/dist/windows/" in f"/{lower_path}/" or lower_path.endswith("/windows"):
        return "windows"
    if "/dist/linux/" in f"/{lower_path}/" or lower_path.endswith("/linux"):
        return "linux"
    return "windows" if os.name == "nt" else "linux"


def _default_package_script_for_platform(platform_name: str) -> str:
    if platform_name == "linux":
        return "packaging/linux/package-linux.sh"
    return "tools/scripts/package-windows.ps1"


def _resolve_openssl_bin(openssl_bin: str, required: bool) -> str:
    raw = str(openssl_bin or "").strip() or "openssl"
    explicit = Path(raw)
    if explicit.is_absolute() or ("\\" in raw or "/" in raw):
        if explicit.exists() and explicit.is_file():
            return str(explicit)
        if required:
            raise FileNotFoundError(
                f"OpenSSL executable not found: {explicit}. Use --openssl-bin <path>."
            )
        return raw

    resolved = shutil.which(raw)
    if resolved:
        return resolved

    if os.name == "nt":
        candidates = [
            Path(r"C:\Program Files\OpenSSL-Win64\bin\openssl.exe"),
            Path(r"C:\Program Files (x86)\OpenSSL-Win32\bin\openssl.exe"),
            Path(os.environ.get("ProgramFiles", ""))
            / "OpenSSL-Win64"
            / "bin"
            / "openssl.exe",
            Path(os.environ.get("ProgramFiles(x86)", ""))
            / "OpenSSL-Win32"
            / "bin"
            / "openssl.exe",
        ]
        for candidate in candidates:
            if str(candidate).strip() and candidate.exists() and candidate.is_file():
                return str(candidate)

    if required:
        raise FileNotFoundError(
            "OpenSSL executable was not found in PATH or common install locations. "
            "Use --openssl-bin <path>."
        )
    return raw


def _extract_rsa_public_key_components(
    public_key: Path, openssl_bin: str
) -> tuple[int, int]:
    cmd = [openssl_bin, "rsa", "-pubin", "-in", str(public_key), "-text", "-noout"]
    completed = subprocess.run(cmd, check=False, capture_output=True, text=True)
    if completed.returncode != 0:
        stderr = (completed.stderr or "").strip()
        raise RuntimeError(
            f"openssl public-key parse failed ({completed.returncode}): {stderr}"
        )
    text = completed.stdout or ""
    modulus_match = re.search(r"Modulus:\s*(.*?)\s*Exponent:", text, flags=re.DOTALL)
    exponent_match = re.search(r"Exponent:\s*(\d+)", text)
    if modulus_match is None or exponent_match is None:
        raise RuntimeError(
            "Could not parse RSA modulus/exponent from public key output."
        )
    modulus_hex = re.sub(r"[^0-9a-fA-F]", "", modulus_match.group(1))
    if not modulus_hex:
        raise RuntimeError("Parsed empty RSA modulus.")
    modulus = int(modulus_hex, 16)
    exponent = int(exponent_match.group(1))
    return modulus, exponent


def _replace_or_insert_key_entry(
    block: str, key_id: str, modulus: int, exponent: int
) -> str:
    entry_pattern = re.compile(
        rf'(^\s*"{re.escape(key_id)}":\s*\(\s*\n)(.*?)(^\s*\),\s*$)',
        flags=re.MULTILINE | re.DOTALL,
    )
    replacement_body = f"{modulus},\n        {exponent},\n"
    if entry_pattern.search(block):
        return entry_pattern.sub(
            lambda match: f"{match.group(1)}{replacement_body}{match.group(3)}",
            block,
            count=1,
        )
    insert_at = block.rfind("}")
    if insert_at < 0:
        raise RuntimeError("Could not locate closing brace in key registry block.")
    entry_text = f'    "{key_id}": (\n        {modulus},\n        {exponent},\n    ),\n'
    return block[:insert_at] + entry_text + block[insert_at:]


def _upsert_public_key_in_registry(
    registry_file: Path,
    key_id: str,
    modulus: int,
    exponent: int,
    registry_name: str = "UPDATE_MANIFEST_PUBLIC_KEYS",
) -> None:
    text = registry_file.read_text(encoding="utf-8")
    original_mode = stat.S_IMODE(registry_file.stat().st_mode)
    marker = f"{registry_name}: dict[str, tuple[int, int]] = {{"
    start = text.find(marker)
    if start < 0:
        raise RuntimeError(f"Could not find key registry marker in {registry_file}")
    open_brace = text.find("{", start)
    if open_brace < 0:
        raise RuntimeError(
            f"Could not find key registry opening brace in {registry_file}"
        )
    depth = 0
    close_brace = -1
    for index in range(open_brace, len(text)):
        ch = text[index]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                close_brace = index
                break
    if close_brace < 0:
        raise RuntimeError(
            f"Could not find key registry closing brace in {registry_file}"
        )
    block = text[open_brace : close_brace + 1]
    updated_block = _replace_or_insert_key_entry(block, key_id, modulus, exponent)
    updated_text = text[:open_brace] + updated_block + text[close_brace + 1 :]
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=registry_file.parent,
            prefix=f".{registry_file.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            temp_file.write(updated_text)
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.chmod(temp_path, original_mode)
        os.replace(temp_path, registry_file)
    finally:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)


def build_update_package(args: argparse.Namespace) -> tuple[Path, Path]:
    package_root = Path(args.package_root).resolve()
    package_platform = _resolve_package_platform(args.package_platform, package_root)
    if not args.skip_package_build:
        package_script_raw = str(
            args.package_script or ""
        ).strip() or _default_package_script_for_platform(package_platform)
        package_script = Path(package_script_raw).resolve()
        if package_platform == "linux":
            _build_linux_package(package_script, package_root)
        else:
            _build_windows_package(package_script, package_root)
    if not package_root.exists() or not package_root.is_dir():
        raise FileNotFoundError(f"Package root does not exist: {package_root}")

    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    payload_path = output_dir / args.payload_name
    manifest_path = output_dir / args.manifest_name

    if (payload_path.exists() or manifest_path.exists()) and not args.overwrite:
        raise FileExistsError(
            "Output exists. Use --overwrite or choose a different output dir/payload name."
        )

    staged_root = _prepare_cross_platform_payload(package_root, package_platform)
    try:
        _zip_directory(staged_root, payload_path)
    finally:
        shutil.rmtree(staged_root.parent, ignore_errors=True)
    payload_sha256 = _sha256_for_path(payload_path)

    needs_openssl = args.register_public_key or not args.unsigned
    args.openssl_bin = _resolve_openssl_bin(args.openssl_bin, required=needs_openssl)

    if args.register_public_key:
        public_key = Path(args.public_key).resolve()
        if not public_key.exists() or not public_key.is_file():
            raise FileNotFoundError(f"Public key not found: {public_key}")
        registry_file = Path(args.key_registry_file).resolve()
        if not registry_file.exists() or not registry_file.is_file():
            raise FileNotFoundError(
                f"Key registry source file not found: {registry_file}"
            )
        modulus, exponent = _extract_rsa_public_key_components(
            public_key, args.openssl_bin
        )
        _upsert_public_key_in_registry(registry_file, args.key_id, modulus, exponent)

    preserve_paths = _normalize_preserve_paths(
        [item.strip() for item in args.preserve_paths.split(",") if item.strip()],
        package_platform,
    )
    manifest: dict = {
        "version": args.version,
        "payload": {
            "path": args.payload_manifest_path or args.payload_name,
            "sha256": payload_sha256,
        },
        "install": {
            "mode": args.install_mode,
            "target_path": args.install_target_path,
            "preserve_paths": preserve_paths,
        },
        "health_check": {
            "type": args.health_check_type,
            "path": args.health_check_path,
        },
    }

    if not args.unsigned:
        private_key = Path(args.private_key).resolve() if args.private_key else None
        if private_key is None:
            raise ValueError("--private-key is required unless --unsigned is used")
        if not private_key.exists() or not private_key.is_file():
            raise FileNotFoundError(f"Private key not found: {private_key}")
        canonical_bytes = _canonical_manifest_bytes(manifest)
        signature = _sign_with_openssl(canonical_bytes, private_key, args.openssl_bin)
        manifest["signature"] = {"key_id": args.key_id, "value": signature}

    _write_json(manifest_path, manifest)
    return payload_path, manifest_path


def _default_version() -> str:
    version_file = _repo_root() / "VERSION"
    if not version_file.exists():
        raise FileNotFoundError(f"VERSION file not found: {version_file}")
    version = version_file.read_text(encoding="utf-8").strip()
    if not version:
        raise ValueError(f"VERSION file is empty: {version_file}")
    return version


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create update zip payload and signed update-manifest.json."
    )
    parser.add_argument(
        "--package-root", required=True, help="Path to packaged app root."
    )
    parser.add_argument(
        "--package-script",
        default="",
        help="Optional package builder script path. Defaults by platform (Windows/Linux).",
    )
    parser.add_argument(
        "--package-platform",
        choices=["auto", "windows", "linux"],
        default="auto",
        help="Package builder platform selection (default: auto).",
    )
    parser.add_argument(
        "--skip-package-build",
        action="store_true",
        help="Skip invoking package builder script before update artifact creation.",
    )
    parser.add_argument("--output-dir", default="dist/update", help="Output directory.")
    parser.add_argument(
        "--version", default="", help="Target app version. Defaults to VERSION file."
    )
    parser.add_argument(
        "--payload-name",
        default="",
        help="Payload zip filename. Default: lanlauncherng-update-<version>.zip",
    )
    parser.add_argument(
        "--payload-manifest-path",
        default="",
        help="Optional payload.path value written to manifest (default: payload filename).",
    )
    parser.add_argument(
        "--manifest-name",
        default="update-manifest.json",
        help="Manifest filename (default: update-manifest.json).",
    )
    parser.add_argument(
        "--install-mode",
        choices=["noop", "directory_swap"],
        default="directory_swap",
    )
    parser.add_argument(
        "--install-target-path",
        default=".",
        help="Install target path written to manifest install.target_path.",
    )
    parser.add_argument(
        "--preserve-paths",
        default="data",
        help="Comma-separated preserve paths for manifest install.preserve_paths.",
    )
    parser.add_argument(
        "--health-check-type",
        choices=["none", "file_exists"],
        default="none",
    )
    parser.add_argument(
        "--health-check-path",
        default="",
        help="Manifest health_check.path value (required for file_exists).",
    )
    parser.add_argument(
        "--key-id", default="llng-root-2026", help="Manifest signature key_id."
    )
    parser.add_argument(
        "--private-key",
        default="secrets/llng-update-private.pem",
        help="Path to RSA private key in PEM format for openssl signing.",
    )
    parser.add_argument(
        "--public-key",
        default="secrets/llng-update-public.pem",
        help="Path to RSA public key in PEM format for registry automation.",
    )
    parser.add_argument(
        "--register-public-key",
        action="store_true",
        help="Upsert public key into launcher key registry source file.",
    )
    parser.add_argument(
        "--key-registry-file",
        default="src/core/service/app.py",
        help="Source file containing UPDATE_MANIFEST_PUBLIC_KEYS registry.",
    )
    parser.add_argument(
        "--openssl-bin", default="openssl", help="openssl command path."
    )
    parser.add_argument(
        "--unsigned", action="store_true", help="Skip signature generation."
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="Overwrite existing outputs."
    )
    args = parser.parse_args(argv)

    args.version = args.version.strip() or _default_version()
    args.payload_name = (
        args.payload_name.strip() or f"lanlauncherng-update-{args.version}.zip"
    )
    if (
        args.health_check_type == "file_exists"
        and not str(args.health_check_path).strip()
    ):
        parser.error(
            "--health-check-path is required when --health-check-type=file_exists"
        )
    return args


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    args = parse_args(argv)
    payload_path, manifest_path = build_update_package(args)
    print(f"Created update payload: {payload_path}")
    print(f"Created update manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
