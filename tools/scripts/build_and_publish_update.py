"""Bump VERSION, build an update package, and publish it to LLNGUPDATEFOLDER."""

from __future__ import annotations

import argparse
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


VERSION_PATTERN = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


def repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def read_dotenv(path: Path) -> dict[str, str]:
    """Read simple KEY=VALUE entries without adding a dotenv dependency."""
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        if key:
            values[key] = value
    return values


def resolve_update_folder(root: Path, environ: dict[str, str] | None = None) -> Path:
    env = dict(os.environ if environ is None else environ)
    value = env.get("LLNGUPDATEFOLDER") or read_dotenv(root / ".env").get("LLNGUPDATEFOLDER")
    if not value:
        raise RuntimeError(
            "LLNGUPDATEFOLDER is not set. Add it to .env or the process environment."
        )
    folder = Path(os.path.expandvars(os.path.expanduser(value))).resolve()
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def bump_patch_version(version: str) -> str:
    match = VERSION_PATTERN.fullmatch(version.strip())
    if match is None:
        raise ValueError(f"VERSION must use MAJOR.MINOR.PATCH format, got: {version!r}")
    major, minor, patch = (int(part) for part in match.groups())
    return f"{major}.{minor}.{patch + 1}"


def write_version(path: Path, version: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    temporary.write_text(version + "\n", encoding="utf-8")
    os.replace(temporary, path)


def publish_artifacts(payload: Path, manifest: Path, destination: Path) -> tuple[Path, Path]:
    """Copy artifacts atomically so readers never observe a partial update."""
    destination.mkdir(parents=True, exist_ok=True)
    published: list[Path] = []
    for source in (payload, manifest):
        if not source.is_file():
            raise FileNotFoundError(f"Update artifact not found: {source}")
        target = destination / source.name
        with tempfile.NamedTemporaryFile(
            dir=destination, prefix=f".{source.name}.", suffix=".tmp", delete=False
        ) as handle:
            temporary = Path(handle.name)
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        published.append(target)
    return published[0], published[1]


def build_update(root: Path, version: str, package_platform: str) -> tuple[Path, Path]:
    output_dir = root / "dist" / package_platform / "update"
    package_root = root / "dist" / package_platform / "lanlauncherng"
    package_script = (
        "packaging/linux/package-linux.sh"
        if package_platform == "linux"
        else "tools/scripts/package-windows.ps1"
    )
    command = [
        sys.executable,
        str(root / "tools/scripts/build_update_package.py"),
        "--package-root",
        str(package_root),
        "--output-dir",
        str(output_dir),
        "--package-platform",
        package_platform,
        "--package-script",
        str(root / package_script),
        "--version",
        version,
        "--key-id",
        os.environ.get("LLNGUPDATEKEYID", "llng-root-2026"),
        "--private-key",
        os.environ.get("LLNGUPDATEPRIVATEKEY", "secrets/llng-update-private.pem"),
        "--public-key",
        os.environ.get("LLNGUPDATEPUBLICKEY", "secrets/llng-update-public.pem"),
        "--register-public-key",
        "--overwrite",
    ]
    subprocess.run(command, cwd=root, check=True)
    payload = output_dir / f"lanlauncherng-update-{version}.zip"
    manifest = output_dir / "update-manifest.json"
    if not payload.is_file() or not manifest.is_file():
        raise FileNotFoundError("Update builder did not create payload and manifest")
    return payload, manifest


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", choices=("auto", "linux", "windows"), default="auto")
    parser.add_argument("--no-publish", action="store_true", help="Build locally without copying to LLNGUPDATEFOLDER")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    root = repo_root()
    version_file = root / "VERSION"
    old_version = version_file.read_text(encoding="utf-8").strip()
    new_version = bump_patch_version(old_version)
    update_folder = None if args.no_publish else resolve_update_folder(root)
    package_platform = args.platform
    if package_platform == "auto":
        package_platform = "windows" if platform.system().lower().startswith("win") else "linux"
    write_version(version_file, new_version)
    try:
        payload, manifest = build_update(root, new_version, package_platform)
        if update_folder is not None:
            published_payload, published_manifest = publish_artifacts(payload, manifest, update_folder)
            print(f"Published update payload: {published_payload}")
            print(f"Published update manifest: {published_manifest}")
        print(f"VERSION bumped: {old_version} -> {new_version}")
    except Exception:
        write_version(version_file, old_version)
        raise
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
