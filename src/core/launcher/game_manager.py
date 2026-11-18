"""Game install/update/delete/start lifecycle management."""

from __future__ import annotations

import hashlib
import os
import shlex
import shutil
import subprocess
import tarfile
import tempfile
from configparser import ConfigParser
from configparser import Error as ConfigParserError
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from threading import Lock
from typing import Any, Callable

from src.core.catalog.install_support import InstallSupport
from src.core.catalog.metadata import GameMetadata, MetadataStore
from src.core.catalog.repository import CatalogRepository
from src.core.platform.base import PlatformAdapter


@dataclass(frozen=True)
class GameActionResult:
    ok: bool
    action: str
    game_id: str
    message: str
    details: dict


class GameLifecycleManager:
    def __init__(
        self,
        repo: CatalogRepository,
        platform_adapter: PlatformAdapter,
        install_support: InstallSupport,
        library_path: str,
        unrar_path: str,
        windows_drive_letter: str,
        windows_lan_root: str,
        linux_cmd_wrapper_path: str,
        *,
        metadata_store: MetadataStore | None = None,
        metadata_lookup: Callable[[str], GameMetadata | None] | None = None,
    ):
        self._repo = repo
        self._platform = platform_adapter
        self._support = install_support
        self._metadata_store = metadata_store
        self._metadata_lookup = metadata_lookup
        self._library_path = library_path
        self._unrar_path = Path(unrar_path)
        self._windows_drive_letter = windows_drive_letter
        self._windows_lan_root = windows_lan_root
        self._linux_cmd_wrapper_path = Path(linux_cmd_wrapper_path).resolve(
            strict=False
        )
        self._linux_windows_runtime = "wine"
        self._linux_proton_path = ""
        self._linux_proton_ge_path = ""
        self._local_metadata_stores: dict[str, MetadataStore] = {}
        # Archive extraction is intentionally serialized to avoid multiple heavy
        # unrar processes saturating disk/CPU on the same machine.
        self._archive_extract_lock = Lock()

    def set_library_path(self, library_path: str) -> None:
        # Allows runtime settings updates to redirect where games are managed.
        self._library_path = library_path

    def set_windows_drive_letter(self, drive_letter: str) -> None:
        self._windows_drive_letter = drive_letter

    def set_linux_runtime_settings(
        self, runtime: str, proton_path: str, proton_ge_path: str
    ) -> None:
        self._linux_windows_runtime = str(runtime or "wine").strip().lower()
        self._linux_proton_path = str(proton_path or "").strip()
        self._linux_proton_ge_path = str(proton_ge_path or "").strip()

    def _metadata(self, game_id: str) -> GameMetadata | None:
        if self._metadata_lookup is not None:
            metadata = self._metadata_lookup(game_id)
            if metadata is not None:
                return metadata
        game_root = self._game_dir(game_id)
        for source_root in (game_root / ".ouisync", game_root):
            folder_key = str(source_root)
            folder_store = self._local_metadata_stores.get(folder_key)
            if folder_store is None:
                folder_store = MetadataStore(source_root)
                self._local_metadata_stores[folder_key] = folder_store
            folder_metadata = folder_store.get_game_folder_metadata(game_id)
            if folder_metadata is not None:
                return folder_metadata
        lan_lookup = getattr(self._repo, "lan_game_metadata", None)
        lan_metadata = lan_lookup(game_id) if callable(lan_lookup) else None
        if isinstance(lan_metadata, GameMetadata):
            return lan_metadata
        if self._metadata_store is not None:
            primary = self._metadata_store.get(game_id)
            if primary is not None:
                return primary
        # Keep supporting earlier per-game bundles that used metadata/<game_id>.json.
        local_root = game_root / "metadata"
        local_key = str(local_root)
        store = self._local_metadata_stores.get(local_key)
        if store is None:
            store = MetadataStore(local_root)
            self._local_metadata_stores[local_key] = store
        return store.get(game_id)

    @staticmethod
    def _expand_metadata_arg_placeholders(raw: str, game_dir: Path) -> str:
        game_dir_text = str(game_dir)
        result = str(raw)
        replacements = {
            "GAMEDIR": game_dir_text,
            "GAME_DIR": game_dir_text,
            "GAME_PATH": game_dir_text,
        }
        for key, value in replacements.items():
            result = result.replace(f"${{{key}}}", value)
            result = result.replace(f"${key}", value)
            result = result.replace(f"%{key}%", value)
        return result

    @staticmethod
    def _normalize_task_args(raw: Any) -> list[str]:
        if raw is None:
            return []
        if isinstance(raw, list):
            result: list[str] = []
            for item in raw:
                text = str(item).strip()
                if not text:
                    continue
                try:
                    result.extend(shlex.split(text))
                except ValueError:
                    result.append(text)
            return result
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return []
            try:
                return shlex.split(text)
            except ValueError:
                return [text]
        text = str(raw).strip()
        return [text] if text else []

    @staticmethod
    def _path_is_safe_relative(candidate: Path) -> bool:
        if candidate.is_absolute():
            return False
        return ".." not in candidate.parts

    def _resolve_metadata_game_start(
        self, game_dir: Path, metadata: GameMetadata | None
    ) -> Path | None:
        if metadata is None:
            return None
        raw_file = str(metadata.game_start_file or "").strip()
        if not raw_file:
            return None
        candidate = Path(raw_file.replace("\\", "/"))
        if not self._path_is_safe_relative(candidate):
            return None
        resolved = game_dir / candidate
        if not resolved.is_file():
            return None
        return resolved

    def _metadata_launch_args(
        self, game_id: str, base_args: list[str], metadata: GameMetadata | None
    ) -> list[str]:
        args = list(base_args)
        if metadata is None:
            return args
        game_dir = self._game_dir(game_id)
        for value in metadata.game_start_args:
            expanded = self._expand_metadata_arg_placeholders(str(value), game_dir)
            if not expanded:
                continue
            # Metadata stores argv entries individually; shell parsing would
            # consume Windows path separators and split paths containing spaces.
            args.append(expanded)
        return args

    def _effective_linux_runtime(
        self, metadata_runtime: str = "", runtime_override: str = ""
    ) -> str:
        normalized = (
            str(runtime_override or metadata_runtime or self._linux_windows_runtime)
            .strip()
            .lower()
        )
        if normalized == "windows":
            return "wine"
        if normalized == "auto":
            return self._linux_windows_runtime
        return normalized

    def _linux_runtime_candidates(
        self, runtime_override: str = "", metadata_runtime: str = ""
    ) -> list[str]:
        runtime = self._effective_linux_runtime(metadata_runtime, runtime_override)
        if runtime == "native":
            # Native scripts are handled earlier in the start flow. CMD launchers need
            # a Windows compatibility layer, so we try Proton and finally Wine.
            return ["proton-ge", "proton", "wine"]
        if runtime == "proton":
            return ["proton", "wine"]
        if runtime == "proton-ge":
            return ["proton-ge", "proton", "wine"]
        return ["wine"]

    def _resolve_linux_runtime(
        self,
        game_dir: Path,
        runtime_override: str = "",
        metadata_runtime: str = "",
    ) -> tuple[str, str, str] | None:
        for runtime in self._linux_runtime_candidates(
            runtime_override=runtime_override, metadata_runtime=metadata_runtime
        ):
            if runtime == "wine":
                wine_cmd = shutil.which("wine") or ""
                if wine_cmd:
                    compat_root = game_dir / ".compatdata" / "wine"
                    return ("wine", wine_cmd, str(compat_root))
                continue

            configured = (
                self._linux_proton_ge_path
                if runtime == "proton-ge"
                else self._linux_proton_path
            )
            proton_binary = configured
            if not proton_binary and runtime == "proton":
                proton_binary = shutil.which("proton") or ""
            if not proton_binary:
                continue
            if "/" in proton_binary and not Path(proton_binary).exists():
                continue
            compat_root = game_dir / ".compatdata" / runtime
            return (runtime, proton_binary, str(compat_root))
        return None

    def _build_linux_wrapper_command(
        self,
        script_path: Path,
        launch_args: list[str],
        game_dir: Path,
        runtime_override: str = "",
        metadata_runtime: str = "",
        leave_terminal_open: bool = False,
    ) -> tuple[list[str], dict] | None:
        if not self._linux_cmd_wrapper_path.exists():
            return None
        resolved = self._resolve_linux_runtime(
            game_dir=game_dir,
            runtime_override=runtime_override,
            metadata_runtime=metadata_runtime,
        )
        if resolved is None:
            return None
        runtime, runtime_binary, compat_data_path = resolved
        command = [
            str(self._linux_cmd_wrapper_path),
            "--runtime",
            runtime,
            "--runtime-binary",
            runtime_binary,
        ]
        if compat_data_path:
            command.extend(["--compat-data-path", compat_data_path])
        if leave_terminal_open:
            command.append("--hold-open")
        command.extend([str(script_path), *launch_args])
        details = {
            "runtime": runtime,
            "runtime_binary": runtime_binary,
            "wrapper": str(self._linux_cmd_wrapper_path),
            "leave_terminal_open": leave_terminal_open,
        }
        if compat_data_path:
            details["compat_data_path"] = compat_data_path
        return command, details

    def _format_command_for_console(self, command: list[str]) -> str:
        # Keep shell-safe output formatting so users can copy/paste exact launch calls.
        return " ".join(shlex.quote(part) for part in command)

    def _base_library(self) -> Path:
        if self._platform.platform_name() == "windows" and self._library_path in {
            "",
            "library",
        }:
            return Path(f"{self._windows_drive_letter}:/{self._windows_lan_root}")
        return Path(self._library_path)

    def _game_dir(self, game_id: str) -> Path:
        return self._base_library() / game_id

    def _archive_path(
        self, game_id: str, archive_source_root: Path | None = None
    ) -> Path:
        game_dir = self._game_dir(game_id)
        metadata = self._metadata(game_id)
        if archive_source_root is not None:
            source_root = Path(archive_source_root).resolve(strict=False)
            if metadata is not None and metadata.archive_file:
                candidate = Path(metadata.archive_file.replace("\\", "/"))
                if self._path_is_safe_relative(candidate):
                    resolved = (source_root / candidate).resolve(strict=False)
                    try:
                        resolved.relative_to(source_root)
                    except (OSError, ValueError):
                        pass
                    else:
                        return resolved
            for filename in (
                f"{game_id}.eti",
                f"{game_id}.rar",
                f"{game_id}.tar.gz",
            ):
                candidate = source_root / filename
                if candidate.is_file() and not candidate.is_symlink():
                    return candidate
            return source_root / f"{game_id}.eti"
        if metadata is not None and metadata.archive_file:
            candidate = Path(metadata.archive_file.replace("\\", "/"))
            if not candidate.is_absolute() and ".." not in candidate.parts:
                metadata_root = Path(metadata.source_file).parent if metadata.source_file else game_dir
                if metadata_root.name != ".ouisync":
                    metadata_root = game_dir
                resolved = (metadata_root / candidate).resolve(strict=False)
                try:
                    resolved.relative_to(game_dir.resolve(strict=False))
                except (OSError, ValueError):
                    pass
                else:
                    return resolved
        expected = {
            f"{game_id}.eti".lower(),
            f"{game_id}.rar".lower(),
            f"{game_id}.tar.gz".lower(),
        }
        for archive_root in (game_dir / ".ouisync", game_dir):
            for filename in (f"{game_id}.eti", f"{game_id}.rar", f"{game_id}.tar.gz"):
                candidate = archive_root / filename
                if candidate.is_file():
                    try:
                        candidate.resolve(strict=False).relative_to(
                            game_dir.resolve(strict=False)
                        )
                    except (OSError, ValueError):
                        continue
                    return candidate
            if archive_root.is_dir():
                try:
                    for candidate in archive_root.iterdir():
                        if not candidate.is_file() or candidate.name.lower() not in expected:
                            continue
                        candidate.resolve(strict=False).relative_to(
                            game_dir.resolve(strict=False)
                        )
                        return candidate
                except (OSError, ValueError):
                    pass
        fallback = game_dir / f"{game_id}.eti"
        if fallback.is_symlink():
            try:
                fallback.resolve(strict=False).relative_to(
                    game_dir.resolve(strict=False)
                )
            except (OSError, ValueError):
                return game_dir / f".{game_id}.archive-unavailable"
        return fallback

    def _version_ini_path(self, game_id: str) -> Path:
        return self._game_dir(game_id) / "version.ini"

    def archive_path(self, game_id: str) -> Path:
        return self._archive_path(game_id)

    def _archive_format(self, game_id: str, archive: Path) -> str:
        metadata = self._metadata(game_id)
        configured = str(metadata.archive_format or "").lower() if metadata else ""
        if configured in {"eti", "rar", "tar.gz"}:
            return configured
        name = archive.name.lower()
        if name.endswith(".tar.gz"):
            return "tar.gz"
        if name.endswith(".rar"):
            return "rar"
        if name.endswith(".eti"):
            return "eti"
        return ""

    def _verify_archive_hash(self, game_id: str, archive: Path) -> tuple[bool, str]:
        metadata = self._metadata(game_id)
        expected = str(metadata.archive_sha256 or "").lower() if metadata else ""
        if not expected:
            return True, ""
        digest = hashlib.sha256()
        try:
            with archive.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            return False, str(exc)
        actual = digest.hexdigest()
        return actual == expected, actual

    @staticmethod
    def _safe_tar_relative_name(raw_name: str) -> Path | None:
        """Return a safe relative path for a tar name, or None (``Path('.')`` for the root)."""
        normalized = raw_name.replace("\\", "/")
        posix_path = PurePosixPath(normalized)
        windows_path = PureWindowsPath(raw_name)
        if (
            not normalized
            or posix_path.is_absolute()
            or windows_path.is_absolute()
            or windows_path.drive
            or ".." in posix_path.parts
            or any(part in {"", "."} for part in posix_path.parts)
        ):
            return None
        if not posix_path.parts:
            return Path(".")
        return Path(*posix_path.parts)

    @classmethod
    def _safe_tar_member_path(cls, member: tarfile.TarInfo) -> Path | None:
        # Hard links are accepted here; their target is validated during extraction.
        if not (member.isdir() or member.isfile() or member.islnk()):
            return None
        relative = cls._safe_tar_relative_name(str(member.name or ""))
        if relative == Path(".") and not member.isdir():
            return None
        return relative

    def _extract_tar_gz_safely(
        self,
        archive: Path,
        target: Path,
        output_callback: Callable[[str], None] | None,
    ) -> tuple[bool, str]:
        game_root = self._game_dir(target.parent.name).resolve(strict=False)
        try:
            target_resolved = target.resolve(strict=False)
            target_resolved.relative_to(game_root)
        except (OSError, ValueError):
            return False, "archive_target_invalid"
        if target.is_symlink():
            return False, "archive_target_invalid"

        try:
            with tempfile.TemporaryDirectory(
                prefix=".llng-extract-", dir=str(game_root)
            ) as temporary:
                staging = Path(temporary)
                seen: set[Path] = set()
                regular_files: set[Path] = set()
                with tarfile.open(archive, mode="r:gz") as tar:
                    members = tar.getmembers()
                    for member in members:
                        relative = self._safe_tar_member_path(member)
                        if relative is None or relative in seen:
                            return False, "archive_member_invalid"
                        if relative == Path("."):
                            continue
                        seen.add(relative)
                        staged_path = staging / relative
                        try:
                            staged_path.resolve(strict=False).relative_to(staging)
                        except (OSError, ValueError):
                            return False, "archive_member_invalid"
                        if member.isdir():
                            staged_path.mkdir(parents=True, exist_ok=True)
                            continue
                        if member.islnk():
                            # GNU tar stores files sharing an inode (common in AppDirs) as
                            # hard links to an earlier member. Materialize them as plain
                            # copies of an already staged regular file; never link outside.
                            link_target = self._safe_tar_relative_name(
                                str(member.linkname or "")
                            )
                            if link_target is None or link_target not in regular_files:
                                return False, "archive_member_invalid"
                            staged_path.parent.mkdir(parents=True, exist_ok=True)
                            with (staging / link_target).open("rb") as source_file, staged_path.open("xb") as output:
                                shutil.copyfileobj(source_file, output, length=1024 * 1024)
                            shutil.copymode(staging / link_target, staged_path)
                            regular_files.add(relative)
                            continue
                        source = tar.extractfile(member)
                        if source is None:
                            return False, "archive_member_invalid"
                        staged_path.parent.mkdir(parents=True, exist_ok=True)
                        with source, staged_path.open("xb") as output:
                            shutil.copyfileobj(source, output, length=1024 * 1024)
                        # Keep only the executable bit from the archive (launchers such as
                        # AppRun need it); never carry over setuid/setgid or world-write.
                        os.chmod(
                            staged_path,
                            0o755 if member.mode & 0o100 else 0o644,
                        )
                        regular_files.add(relative)

                target.mkdir(parents=True, exist_ok=True)
                for source_path in sorted(staging.rglob("*")):
                    if source_path.is_symlink():
                        return False, "archive_member_invalid"
                    relative = source_path.relative_to(staging)
                    destination = target / relative
                    try:
                        destination.resolve(strict=False).relative_to(game_root)
                    except (OSError, ValueError):
                        return False, "archive_member_invalid"
                    if source_path.is_dir():
                        if destination.is_symlink() or (destination.exists() and not destination.is_dir()):
                            return False, "archive_target_invalid"
                        destination.mkdir(parents=True, exist_ok=True)
                        continue
                    parent = destination.parent
                    while parent != target and parent != parent.parent:
                        if parent.is_symlink():
                            return False, "archive_target_invalid"
                        parent = parent.parent
                    if destination.is_symlink() or destination.is_dir():
                        return False, "archive_target_invalid"
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(source_path, destination)
        except (OSError, tarfile.TarError, EOFError) as exc:
            self._emit_output(output_callback, f"archive extraction failed: {exc}")
            return False, "archive_extract_failed"
        return True, ""

    def _read_installed_version(self, game_id: str) -> str:
        ini_path = self._version_ini_path(game_id)
        if not ini_path.exists():
            return ""

        try:
            raw = ini_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return ""

        return self._parse_version_text(raw)

    @staticmethod
    def _parse_version_text(raw: str) -> str:

        parser = ConfigParser()
        try:
            parser.read_string(raw)
        except ConfigParserError:
            for line in raw.splitlines():
                value = line.strip()
                if value:
                    return value
            return ""

        # Accept both [version] local=... and flat fallback keys.
        if parser.has_option("version", "local"):
            return parser.get("version", "local")
        if parser.has_option("game", "version"):
            return parser.get("game", "version")
        if parser.defaults().get("version"):
            return str(parser.defaults().get("version"))
        return ""

    def _read_archive_version(
        self, game_id: str, archive: Path, archive_format: str
    ) -> str | None:
        metadata = self._metadata(game_id)
        if (
            metadata is None
            or metadata.game_provider_type != "ouisync"
            or not self._db_version(game_id).strip()
        ):
            return None
        if not metadata.archive_version_file:
            return ""

        version_path = Path(metadata.archive_version_file.replace("\\", "/"))
        if not self._path_is_safe_relative(version_path):
            return ""
        if archive_format == "tar.gz":
            try:
                with tarfile.open(archive, mode="r:gz") as tar:
                    member = tar.getmember(version_path.as_posix())
                    if not member.isfile():
                        return ""
                    source = tar.extractfile(member)
                    if source is None:
                        return ""
                    raw = source.read(64 * 1024).decode("utf-8", errors="replace")
            except (OSError, KeyError, tarfile.TarError, EOFError):
                return ""
            return self._parse_version_text(raw).strip()

        if self._platform.platform_name() == "windows":
            unrar_command = str(self._unrar_path) if self._unrar_path.exists() else ""
        else:
            unrar_command = shutil.which("unrar") or ""
        if not unrar_command:
            return ""
        try:
            result = subprocess.run(
                [unrar_command, "p", "-inul", str(archive), version_path.as_posix()],
                check=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=30,
            )
        except (OSError, subprocess.TimeoutExpired):
            return ""
        if result.returncode != 0:
            return ""
        raw = result.stdout.decode("utf-8", errors="replace")
        return self._parse_version_text(raw).strip()

    def _db_version(self, game_id: str) -> str:
        game = self._repo.get_game(game_id, locale="en")
        if not game:
            return ""
        return str(game.get("version", ""))

    def _write_installed_version_ini(
        self,
        game_id: str,
        output_callback: Callable[[str], None] | None = None,
    ) -> GameActionResult | None:
        version = self._db_version(game_id).strip()
        if not version:
            self._emit_output(
                output_callback, "database version missing, skip version.ini write"
            )
            return None

        version_ini = self._version_ini_path(game_id)
        try:
            # Legacy launcher expects plain one-line version.ini files (no INI sections).
            version_ini.write_text(f"{version}\n", encoding="utf-8")
        except OSError as exc:
            self._emit_output(output_callback, f"version.ini write failed: {exc}")
            return GameActionResult(
                False,
                "install",
                game_id,
                "version_ini_write_failed",
                {"path": str(version_ini), "error": str(exc)},
            )
        self._emit_output(output_callback, f"version.ini updated to {version}")
        return None

    def _emit_output(
        self, output_callback: Callable[[str], None] | None, line: str
    ) -> None:
        if output_callback is None:
            return
        text = str(line).strip()
        if not text:
            return
        output_callback(text)

    def _stream_process_output(
        self,
        proc: subprocess.Popen,
        output_callback: Callable[[str], None] | None,
        output_lines: list[str],
    ) -> None:
        if proc.stdout is None:
            return

        if not hasattr(proc.stdout, "read"):
            for raw_line in proc.stdout:
                line = str(raw_line).rstrip("\r\n")
                if not line:
                    continue
                output_lines.append(line)
                self._emit_output(output_callback, line)
            return

        buffer = ""
        while True:
            chunk = proc.stdout.read(256)
            if not chunk:
                break
            for char in chunk:
                if char in {"\r", "\n"}:
                    line = buffer.strip()
                    buffer = ""
                    if not line:
                        continue
                    output_lines.append(line)
                    self._emit_output(output_callback, line)
                    continue
                buffer += char

        tail = buffer.strip()
        if tail:
            output_lines.append(tail)
            self._emit_output(output_callback, tail)

    def _winetricks_paths(self) -> tuple[str, str]:
        # Keep installer task execution deterministic for both system and provider-provided winetricks.
        base_library = self._base_library()
        provider_root = base_library / "ng_provider" / "tools" / "winetricks"
        provider_binary = provider_root / "winetricks"
        provider_cache = provider_root / "cache"
        provider_cache.mkdir(parents=True, exist_ok=True)
        binary = str(provider_binary)
        if not provider_binary.is_file():
            binary = shutil.which("winetricks") or ""
        return binary, str(provider_cache)

    def _resolve_task_runtime(
        self, game_dir: Path, metadata: GameMetadata | None
    ) -> str:
        runtime_override = metadata.runner if metadata is not None else ""
        resolved = self._resolve_linux_runtime(
            game_dir, metadata_runtime=runtime_override
        )
        if resolved is None:
            return ""
        return resolved[0]

    def _run_winetricks_task(
        self,
        game_id: str,
        metadata: GameMetadata | None,
        task: dict[str, Any],
        output_callback: Callable[[str], None] | None = None,
    ) -> GameActionResult | None:
        package_raw = task.get("app")
        package_parts = self._normalize_task_args(package_raw)
        args_raw = task.get("args")
        arg_parts = self._normalize_task_args(args_raw)
        if not package_parts and arg_parts:
            # Some task files pass package names directly in args.
            package_parts = [part for part in arg_parts if not part.startswith("-")]
            arg_parts = [part for part in arg_parts if part.startswith("-")]

        if not package_parts:
            self._emit_output(
                output_callback,
                "installer task missing package: skipping",
            )
            return None

        game_dir = self._game_dir(game_id)
        if self._platform.platform_name() == "windows":
            self._emit_output(
                output_callback,
                "installer tasks are not supported on Windows; skipping",
            )
            return None

        runtime = self._resolve_task_runtime(game_dir, metadata)
        if not runtime:
            return GameActionResult(
                False,
                "install",
                game_id,
                "install_task_runtime_missing",
                {
                    "task": "winetricks",
                    "error": "runtime_not_available",
                    "packages": package_parts,
                    "metadata_runtime": metadata.runner if metadata is not None else "",
                },
            )

        compat_data_path = str(game_dir / ".compatdata" / runtime)
        winetricks_binary, cache_dir = self._winetricks_paths()
        if not winetricks_binary:
            return GameActionResult(
                False,
                "install",
                game_id,
                "install_task_runtime_missing",
                {
                    "task": "winetricks",
                    "error": "winetricks_not_found",
                    "packages": package_parts,
                },
            )
        resolved_runtime, runtime_binary, _ = self._resolve_linux_runtime(
            game_dir=game_dir, metadata_runtime=runtime
        ) or ("", "", "")
        if not resolved_runtime or not runtime_binary:
            return GameActionResult(
                False,
                "install",
                game_id,
                "install_task_runtime_missing",
                {"task": "winetricks", "error": "runtime_not_available"},
            )
        if not Path(cache_dir).exists():
            Path(cache_dir).mkdir(parents=True, exist_ok=True)

        command = [
            winetricks_binary,
            "-q",
            *arg_parts,
            *package_parts,
        ]
        env = os.environ.copy()
        env["WINEPREFIX"] = compat_data_path
        env["WINETRICKS_CACHE"] = str(cache_dir)
        env["W_CACHE"] = str(cache_dir)
        self._emit_output(
            output_callback,
            f"running installer task winetricks for {game_id}: {' '.join(command)}",
        )
        output_lines: list[str] = []
        popen_kwargs: dict[str, object] = {
            "stdout": subprocess.PIPE,
            "stderr": subprocess.STDOUT,
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",
            "env": env,
        }
        try:
            proc = subprocess.Popen(  # noqa: S603 - command generated by local metadata and local tools
                command,
                **popen_kwargs,
            )
            self._stream_process_output(proc, output_callback, output_lines)
            return_code = proc.wait()
        except OSError as exc:
            return GameActionResult(
                False,
                "install",
                game_id,
                "installer_task_failed",
                {"task": "winetricks", "error": str(exc), "packages": package_parts},
            )

        if return_code != 0:
            return GameActionResult(
                False,
                "install",
                game_id,
                "installer_task_failed",
                {
                    "task": "winetricks",
                    "error": f"exit_code_{return_code}",
                    "packages": package_parts,
                    "command": command,
                    "console_lines": output_lines[-200:],
                },
            )
        self._emit_output(
            output_callback,
            f"installer task completed: {' '.join(command)}",
        )
        return None

    def _run_install_tasks(
        self,
        game_id: str,
        output_callback: Callable[[str], None] | None = None,
    ) -> GameActionResult | None:
        metadata = self._metadata(game_id)
        if metadata is None:
            return None
        tasks = metadata.installer_tasks or []
        if not tasks:
            return None
        for task in tasks:
            if not isinstance(task, dict):
                continue
            name = str(task.get("name") or task.get("action") or "").strip().lower()
            if name in {"winetricks", "protontricks"}:
                result = self._run_winetricks_task(
                    game_id, metadata, task, output_callback
                )
                if result is not None and not result.ok:
                    return result
                continue
            self._emit_output(
                output_callback,
                f"installer task '{name}' is not recognized and will be skipped",
            )
        return None

    def check_status(self, game_id: str) -> GameActionResult:
        game_dir = self._game_dir(game_id)
        archive = self._archive_path(game_id)
        local_dir = game_dir / "local"
        metadata = self._metadata(game_id)
        game_start = (
            self._resolve_metadata_game_start(game_dir, metadata)
            or game_dir / "game_start.cmd"
        )
        server_start = game_dir / "server_start.cmd"

        installed_version = self._read_installed_version(game_id)
        db_version = self._db_version(game_id)
        needs_update = bool(
            db_version and installed_version and db_version != installed_version
        )

        return GameActionResult(
            ok=True,
            action="status",
            game_id=game_id,
            message="ok",
            details={
                "game_dir": str(game_dir),
                "archive_exists": archive.exists(),
                "local_exists": local_dir.exists(),
                "game_start_exists": game_start.exists(),
                "server_start_exists": server_start.exists(),
                "installed_version": installed_version,
                "db_version": db_version,
                "needs_update": needs_update,
            },
        )

    def _extract_archive(
        self,
        game_id: str,
        output_callback: Callable[[str], None] | None = None,
        archive_source_root: Path | None = None,
    ) -> GameActionResult:
        archive = self._archive_path(game_id, archive_source_root)
        target = self._game_dir(game_id) / "local"

        if not archive.exists():
            self._emit_output(output_callback, f"archive missing: {archive}")
            return GameActionResult(
                False, "install", game_id, "archive_missing", {"archive": str(archive)}
            )

        archive_format = self._archive_format(game_id, archive)
        if archive_format not in {"eti", "rar", "tar.gz"}:
            return GameActionResult(
                False, "install", game_id, "archive_format_unsupported", {}
            )
        hash_ok, hash_detail = self._verify_archive_hash(game_id, archive)
        if not hash_ok:
            metadata = self._metadata(game_id)
            return GameActionResult(
                False,
                "install",
                game_id,
                "archive_checksum_mismatch",
                {
                    "expected": metadata.archive_sha256 if metadata else "",
                    "actual": hash_detail,
                },
            )

        archive_version = self._read_archive_version(game_id, archive, archive_format)
        if archive_version is not None:
            expected_version = self._db_version(game_id).strip()
            if archive_version != expected_version:
                self._emit_output(
                    output_callback,
                    f"archive version mismatch: expected {expected_version}, found {archive_version}",
                )
                return GameActionResult(
                    False,
                    "install",
                    game_id,
                    "archive_version_mismatch",
                    {"expected": expected_version, "actual": archive_version},
                )

        tasks_result = self._run_install_tasks(game_id, output_callback=output_callback)
        if tasks_result is not None and not tasks_result.ok:
            return tasks_result

        if archive_format == "tar.gz":
            acquired_immediately = self._archive_extract_lock.acquire(blocking=False)
            if not acquired_immediately:
                self._emit_output(
                    output_callback,
                    "another archive extraction is active, waiting for the extraction slot",
                )
                self._archive_extract_lock.acquire()
            try:
                extracted, detail = self._extract_tar_gz_safely(
                    archive, target, output_callback
                )
            finally:
                self._archive_extract_lock.release()
            if not extracted:
                return GameActionResult(
                    False, "install", game_id, detail, {"archive": str(archive)}
                )
            return self._finish_archive_install(game_id, output_callback)

        unrar_command = ""
        if self._platform.platform_name() == "windows":
            if not self._unrar_path.exists():
                self._emit_output(output_callback, f"unrar missing: {self._unrar_path}")
                return GameActionResult(
                    False,
                    "install",
                    game_id,
                    "unrar_missing",
                    {"unrar": str(self._unrar_path)},
                )
            unrar_command = str(self._unrar_path)
        else:
            # Linux client machines are expected to provide unrar via PATH.
            unrar_command = shutil.which("unrar") or ""
            if not unrar_command:
                self._emit_output(output_callback, "unrar missing: unrar")
                return GameActionResult(
                    False,
                    "install",
                    game_id,
                    "unrar_missing",
                    {"unrar": "unrar"},
                )

        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self._emit_output(output_callback, f"create target failed: {exc}")
            return GameActionResult(
                False,
                "install",
                game_id,
                "local_folder_create_failed",
                {"target": str(target)},
            )

        cmd = [unrar_command, "x", "-o+", "-y", "-ol-", str(archive), str(target)]
        self._emit_output(output_callback, f"extract command: {' '.join(cmd)}")
        output_lines: list[str] = []
        acquired_immediately = self._archive_extract_lock.acquire(blocking=False)
        if not acquired_immediately:
            self._emit_output(
                output_callback,
                "another archive extraction is active, waiting for the extraction slot",
            )
            self._archive_extract_lock.acquire()
        try:
            self._emit_output(output_callback, "archive extraction started")
            popen_kwargs: dict[str, object] = {
                "stdout": subprocess.PIPE,
                "stderr": subprocess.STDOUT,
                "text": True,
                "encoding": "utf-8",
                "errors": "replace",
            }
            if self._platform.platform_name() == "windows":
                startup_info_ctor = getattr(subprocess, "STARTUPINFO", None)
                if startup_info_ctor is not None:
                    startup_info = startup_info_ctor()
                    startup_info.dwFlags |= getattr(
                        subprocess, "STARTF_USESHOWWINDOW", 0
                    )
                    startup_info.wShowWindow = getattr(subprocess, "SW_HIDE", 0)
                    popen_kwargs["startupinfo"] = startup_info
                popen_kwargs["creationflags"] = getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            try:
                proc = subprocess.Popen(  # noqa: S603 - command is built from local bundled binary and game files
                    cmd,
                    **popen_kwargs,
                )
                self._stream_process_output(proc, output_callback, output_lines)
                return_code = proc.wait()
            except OSError as exc:
                self._emit_output(output_callback, str(exc))
                return GameActionResult(
                    False, "install", game_id, str(exc), {"cmd": cmd}
                )
        finally:
            self._archive_extract_lock.release()

        if return_code != 0:
            self._emit_output(output_callback, f"extract failed: exit={return_code}")
            return GameActionResult(
                False,
                "install",
                game_id,
                "unrar_failed",
                {"code": return_code, "console_lines": output_lines[-200:]},
            )

        return self._finish_archive_install(game_id, output_callback)

    def _finish_archive_install(
        self,
        game_id: str,
        output_callback: Callable[[str], None] | None = None,
    ) -> GameActionResult:
        local_dir = self._game_dir(game_id) / "local"
        if not local_dir.exists():
            self._emit_output(
                output_callback, f"missing local folder after extract: {local_dir}"
            )
            return GameActionResult(
                False, "install", game_id, "local_folder_missing_after_extract", {}
            )

        setup_result = self._run_game_setup(game_id, output_callback=output_callback)
        if setup_result is not None and not setup_result.ok:
            return setup_result

        version_write_result = self._write_installed_version_ini(
            game_id, output_callback=output_callback
        )
        if version_write_result is not None and not version_write_result.ok:
            return version_write_result

        self._emit_output(output_callback, "extract/install completed")
        return GameActionResult(True, "install", game_id, "installed", {})

    def _run_game_setup(
        self,
        game_id: str,
        output_callback: Callable[[str], None] | None = None,
    ) -> GameActionResult | None:
        game_dir = self._game_dir(game_id)
        setup_cmd = game_dir / "game_setup.cmd"
        setup_sh = game_dir / "game_setup.sh"

        command: list[str] | None = None
        script_path = ""
        run_kwargs: dict[str, object] = {
            "check": False,
            "cwd": str(game_dir),
        }
        if self._platform.platform_name() == "windows":
            if not setup_cmd.exists():
                return None
            script_path = str(setup_cmd)
            command = ["cmd.exe", "/c", script_path]
            # Dedicated console keeps setup prompts usable during watchdog installs.
            run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        else:
            if setup_sh.exists():
                script_path = str(setup_sh)
                command = ["bash", script_path]
            elif setup_cmd.exists():
                wrapper_call = self._build_linux_wrapper_command(
                    setup_cmd,
                    [],
                    game_dir,
                    runtime_override="wine",
                )
                if wrapper_call is None:
                    self._emit_output(
                        output_callback,
                        (
                            "setup failed: no usable linux runtime for windows scripts "
                            f"({self._linux_cmd_wrapper_path})"
                        ),
                    )
                    return GameActionResult(
                        False,
                        "install",
                        game_id,
                        "game_setup_failed",
                        {
                            "script": str(setup_cmd),
                            "wrapper": str(self._linux_cmd_wrapper_path),
                            "error": "linux_windows_runtime_unavailable",
                        },
                    )
                script_path = str(setup_cmd)
                command = wrapper_call[0]
            else:
                return None

        self._emit_output(output_callback, f"run setup: {script_path}")
        try:
            # Wait for setup completion so install state does not flip to installed too early.
            completed = subprocess.run(  # noqa: S603 - local game setup scripts in managed library
                command,
                **run_kwargs,
            )
        except OSError as exc:
            self._emit_output(output_callback, f"setup failed: {exc}")
            return GameActionResult(
                False,
                "install",
                game_id,
                "game_setup_failed",
                {"script": script_path, "error": str(exc)},
            )
        if completed.returncode != 0:
            self._emit_output(
                output_callback, f"setup failed: exit={completed.returncode}"
            )
            return GameActionResult(
                False,
                "install",
                game_id,
                "game_setup_failed",
                {"script": script_path, "code": int(completed.returncode)},
            )
        self._emit_output(output_callback, "setup command completed")
        return None

    def install(
        self,
        game_id: str,
        output_callback: Callable[[str], None] | None = None,
        archive_source_root: Path | None = None,
    ) -> GameActionResult:
        return self._extract_archive(
            game_id,
            output_callback=output_callback,
            archive_source_root=archive_source_root,
        )

    def update(
        self,
        game_id: str,
        output_callback: Callable[[str], None] | None = None,
        archive_source_root: Path | None = None,
    ) -> GameActionResult:
        status = self.check_status(game_id) if archive_source_root is None else None
        if status is not None and not status.details.get("archive_exists"):
            return GameActionResult(
                False, "update", game_id, "archive_missing", status.details
            )
        return self._extract_archive(
            game_id,
            output_callback=output_callback,
            archive_source_root=archive_source_root,
        )

    def uninstall(self, game_id: str) -> GameActionResult:
        game_dir = self._game_dir(game_id)
        local_dir = game_dir / "local"

        if local_dir.exists() and local_dir.is_dir():
            shutil.rmtree(local_dir, ignore_errors=False)

        # Remove known launch helper scripts while preserving synced archive payload.
        for script_name in ("game_start.cmd", "server_start.cmd"):
            script = game_dir / script_name
            if script.exists():
                script.unlink()

        return GameActionResult(
            True, "uninstall", game_id, "uninstalled", {"game_dir": str(game_dir)}
        )

    def start_game(
        self,
        game_id: str,
        server: bool = False,
        game_lang: str = "en",
        player: str = "",
        linux_runtime_override: str = "",
        linux_leave_terminal_open: bool = False,
    ) -> GameActionResult:
        status = self.check_status(game_id)
        if not bool(status.details.get("local_exists", False)):
            if not bool(status.details.get("archive_exists", False)):
                return GameActionResult(
                    False,
                    "start",
                    game_id,
                    "local_missing_and_archive_missing",
                    status.details,
                )
            recovery = self.install(game_id)
            if not recovery.ok:
                return GameActionResult(
                    False,
                    "start",
                    game_id,
                    "start_install_recovery_failed",
                    {
                        "install_message": recovery.message,
                        "install_details": recovery.details,
                    },
                )

        game_dir = self._game_dir(game_id)
        metadata = self._metadata(game_id)
        cmd_script = game_dir / ("server_start.cmd" if server else "game_start.cmd")
        sh_script = game_dir / ("server_start.sh" if server else "game_start.sh")
        if not server:
            override = self._resolve_metadata_game_start(game_dir, metadata)
            if override is not None:
                if override.suffix.lower() == ".sh" and self._platform.platform_name() == "linux":
                    sh_script = override
                else:
                    cmd_script = override
        launch_args = self._metadata_launch_args(
            game_id,
            [str(game_dir), game_id, game_lang, player],
            metadata,
        )
        metadata_runtime = str(metadata.runner if metadata is not None else "")

        # Linux prefers native shell launchers and falls back to CMD wrapper when only .cmd exists.
        if self._platform.platform_name() == "linux":
            if sh_script.exists():
                full_command = [str(sh_script), *launch_args]
                result = self._platform.launch_executable(
                    str(sh_script), args=launch_args
                )
                return GameActionResult(
                    result.ok,
                    "start",
                    game_id,
                    result.message,
                    {
                        "script": str(sh_script),
                        "launch_method": "linux_native_script",
                        "runtime": "native",
                        "launch_command": full_command,
                        "launch_command_display": self._format_command_for_console(
                            full_command
                        ),
                    },
                )

            wrapper_call = self._build_linux_wrapper_command(
                cmd_script,
                launch_args,
                game_dir,
                runtime_override=linux_runtime_override,
                metadata_runtime=metadata_runtime if not server else "",
                leave_terminal_open=linux_leave_terminal_open,
            )
            if cmd_script.exists() and wrapper_call is not None:
                full_command = [wrapper_call[0][0], *wrapper_call[0][1:]]
                result = self._platform.launch_executable(
                    wrapper_call[0][0],
                    args=wrapper_call[0][1:],
                )
                return GameActionResult(
                    result.ok,
                    "start",
                    game_id,
                    result.message,
                    {
                        "script": str(cmd_script),
                        "launch_method": "linux_cmd_wrapper",
                        "launch_command": full_command,
                        "launch_command_display": self._format_command_for_console(
                            full_command
                        ),
                        **wrapper_call[1],
                    },
                )

            if cmd_script.exists():
                return GameActionResult(
                    False,
                    "start",
                    game_id,
                    "linux_windows_runtime_unavailable",
                    {
                        "script": str(cmd_script),
                        "wrapper": str(self._linux_cmd_wrapper_path),
                        "runtime": str(
                            linux_runtime_override or self._linux_windows_runtime
                        ),
                    },
                )

            return GameActionResult(
                False,
                "start",
                game_id,
                "start_script_missing",
                {
                    "cmd": str(cmd_script),
                    "sh": str(sh_script),
                    "wrapper": str(self._linux_cmd_wrapper_path),
                },
            )

        if not cmd_script.exists():
            return GameActionResult(
                False,
                "start",
                game_id,
                "start_script_missing",
                {"script": str(cmd_script)},
            )

        result = self._platform.launch_executable(str(cmd_script), args=launch_args)
        full_command = [str(cmd_script), *launch_args]
        return GameActionResult(
            result.ok,
            "start",
            game_id,
            result.message,
            {
                "script": str(cmd_script),
                "args": launch_args,
                "launch_method": "windows_cmd",
                "runtime": "native",
                "launch_command": full_command,
                "launch_command_display": self._format_command_for_console(
                    full_command
                ),
            },
        )
