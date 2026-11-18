"""Offline trust registry and signature checks for OpenSourceGameIndex."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import tempfile
import time
from pathlib import Path
from typing import Any

_SHA256_DIGEST_INFO_PREFIX = bytes.fromhex("3031300d060960864801650304020105000420")
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_HEX_MODULUS_RE = re.compile(r"^(?:[A-Fa-f0-9]{2}){256,512}$")
_MAX_REGISTRY_BYTES = 1_048_576
_MAX_SIGNATURE_TEXT_LENGTH = 1024

# Provisioned at release time from the offline catalog-root public key. Never
# reuse update-manifest keys here; an empty set intentionally fails closed.
GAME_CATALOG_ROOT_PUBLIC_KEYS: dict[str, tuple[int, int]] = {
    "llng-catalog-root-2026": (
        5340248600395246209841471686909756707728544246372105026684950058358855836523171780510521812554778220599059527874305359288676224988939754693114439555565926628982060574519582428760674137501429650845695675635649674575256979144526655517220482798830178744784523925779382493541265058985739205820614723789482909376460254780721464337932546129743956261563836794140725341656097745304970213356108987838476585821952103948352152961389158066459362967383553063599198436419479264686686802421589851984761276291742500443425661275137074020430119761642985320913953753809158172347662249581183757048302895338704010879640671169433849357985167543235164351608567548571628881975743460063950515955338477462316366883102765019862959067008074289352673774310917035759160819698095140988354313218299409149264286792608219757686347333532493645473996857789467910001875100422765684373299052642595938181182894811154023818718023948328064486447612588137008226148813,
        65537,
    ),
}


def canonical_signed_bytes(payload: dict[str, Any]) -> bytes:
    unsigned_payload = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(
        unsigned_payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def strict_json_loads(raw: str) -> Any:
    def object_without_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate_json_key")
            result[key] = value
        return result

    def reject_constant(_value: str) -> None:
        raise ValueError("invalid_json_constant")

    return json.loads(
        raw,
        object_pairs_hook=object_without_duplicates,
        parse_constant=reject_constant,
    )


def verify_rsa_sha256_signature(
    signed_bytes: bytes, signature: bytes, modulus: int, exponent: int
) -> bool:
    """Verify strict PKCS#1 v1.5 SHA-256 using public-key-only stdlib math."""
    if modulus <= 0 or exponent < 3 or exponent % 2 == 0:
        return False
    key_size = (modulus.bit_length() + 7) // 8
    if len(signature) != key_size:
        return False
    signature_value = int.from_bytes(signature, byteorder="big")
    if signature_value >= modulus:
        return False
    decoded = pow(signature_value, exponent, modulus).to_bytes(key_size, byteorder="big")
    digest_info = _SHA256_DIGEST_INFO_PREFIX + hashlib.sha256(signed_bytes).digest()
    padding_size = key_size - len(digest_info) - 3
    if padding_size < 8:
        return False
    expected = b"\x00\x01" + (b"\xff" * padding_size) + b"\x00" + digest_info
    return decoded == expected


def _document_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()


def accept_monotonic_revision(
    payload: dict[str, Any], revision_key: str, state_path: str | Path
) -> bool:
    revision = payload.get(revision_key)
    if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
        return False
    path = Path(state_path)
    try:
        path.stat()
    except FileNotFoundError:
        state = None
    except OSError:
        return False
    else:
        try:
            if path.stat().st_size > _MAX_REGISTRY_BYTES:
                return False
            loaded_state = strict_json_loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return False
        state = loaded_state if isinstance(loaded_state, dict) else None
        if (
            state is None
            or set(state) != {"sequence", "digest"}
            or isinstance(state.get("sequence"), bool)
            or not isinstance(state.get("sequence"), int)
            or state["sequence"] < 1
            or not isinstance(state.get("digest"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", state["digest"])
        ):
            return False
    digest = _document_digest(payload)
    current_revision = state.get("sequence") if state else None
    current_digest = state.get("digest") if state else None
    if current_revision is not None and (
        revision < current_revision
        or (revision == current_revision and digest != current_digest)
    ):
        return False
    if state is None or revision > current_revision:
        return _atomic_write_json(path, {"sequence": revision, "digest": digest})
    return True


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> bool:
    temp_path: Path | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            json.dump(payload, temp_file, sort_keys=True, separators=(",", ":"))
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_path = Path(temp_file.name)
        os.replace(temp_path, path)
        return True
    except OSError:
        return False
    finally:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass


class PublisherTrustStore:
    """Validate root-signed publisher registries and persist anti-rollback state."""

    def __init__(
        self,
        *,
        root_public_keys: dict[str, tuple[int, int]] | None,
        cache_path: str | Path,
        state_path: str | Path,
        registry_path: str | Path | None = None,
    ) -> None:
        self._root_public_keys = dict(root_public_keys or {})
        self._cache_path = Path(cache_path)
        self._state_path = Path(state_path)
        self._registry_path = Path(registry_path).resolve(strict=False) if registry_path else None
        self._last_registry_signature: tuple[str, int, int, int, int] | None = None
        self._cached_keys: dict[str, dict[str, Any]] | None = None

    def load(self, registry_path: str | Path | None) -> dict[str, dict[str, Any]] | None:
        candidate = self._read_stable(Path(registry_path)) if registry_path else None
        keys = self._accept(candidate) if candidate is not None else None
        if keys is not None:
            return keys
        cached = self._read_document(self._cache_path)
        if cached is None:
            return None
        return self._accept(cached)

    def registry_signature(self) -> tuple[str, int, int, int, int] | None:
        return self._last_registry_signature

    def current_registry_signature(self) -> tuple[str, int, int, int, int] | None:
        return self._stat(self._registry_path) if self._registry_path else None

    def set_registry_path(self, registry_path: str | Path | None) -> None:
        path = Path(registry_path).resolve(strict=False) if registry_path else None
        self._registry_path = path
        self._last_registry_signature = self._stat(path) if path else None
        self._cached_keys = None

    def _read_stable(self, path: Path) -> dict[str, Any] | None:
        for attempt in range(3):
            before = self._stat(path)
            if before is None:
                return None
            if before[2] > _MAX_REGISTRY_BYTES:
                return None
            try:
                raw = path.read_text(encoding="utf-8")
                if len(raw.encode("utf-8")) > _MAX_REGISTRY_BYTES:
                    return None
                payload = strict_json_loads(raw)
            except (OSError, UnicodeError, ValueError):
                payload = None
            after = self._stat(path)
            if isinstance(payload, dict) and before == after:
                self._last_registry_signature = after
                return payload
            if attempt < 2:
                time.sleep(0.05 * (attempt + 1))
        self._last_registry_signature = self._stat(path)
        return None

    @staticmethod
    def _stat(path: Path) -> tuple[str, int, int, int, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (
            str(path),
            int(stat.st_mtime_ns),
            int(stat.st_size),
            int(getattr(stat, "st_dev", 0)),
            int(getattr(stat, "st_ino", 0)),
        )

    @staticmethod
    def _read_document(path: Path) -> dict[str, Any] | None:
        try:
            if path.stat().st_size > _MAX_REGISTRY_BYTES:
                return None
            payload = strict_json_loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError):
            return None
        return payload if isinstance(payload, dict) else None

    def _accept(
        self, payload: dict[str, Any], *, persist: bool = True
    ) -> dict[str, dict[str, Any]] | None:
        sequence = payload.get("sequence")
        signature = payload.get("signature")
        if (
            isinstance(payload.get("schema_version"), bool)
            or payload.get("schema_version") != 1
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
            or set(payload) != {"schema_version", "sequence", "issued_at_utc", "keys", "signature"}
            or not isinstance(payload.get("issued_at_utc"), str)
            or not 20 <= len(payload["issued_at_utc"]) <= 40
            or not isinstance(signature, dict)
            or set(signature) != {"key_id", "value"}
        ):
            return None
        root_key_id = signature.get("key_id")
        signature_value = signature.get("value")
        root_key = (
            self._root_public_keys.get(root_key_id)
            if isinstance(root_key_id, str) and _KEY_ID_RE.fullmatch(root_key_id)
            else None
        )
        if (
            root_key is None
            or not isinstance(signature_value, str)
            or not 344 <= len(signature_value) <= _MAX_SIGNATURE_TEXT_LENGTH
        ):
            return None
        try:
            signature_bytes = base64.b64decode(signature_value, validate=True)
        except (ValueError, TypeError):
            return None
        if not verify_rsa_sha256_signature(
            canonical_signed_bytes(payload), signature_bytes, root_key[0], root_key[1]
        ):
            return None

        keys = payload.get("keys")
        if not isinstance(keys, list) or not 1 <= len(keys) <= 256:
            return None
        validated: dict[str, dict[str, Any]] = {}
        for raw in keys:
            parsed = self._parse_publisher_key(raw, sequence)
            if parsed is None or parsed[0] in validated:
                return None
            validated[parsed[0]] = parsed[1]

        digest = _document_digest(payload)
        state, state_valid = self._read_state()
        if not state_valid:
            return None
        current_sequence = state.get("sequence") if state else None
        current_digest = state.get("digest") if state else None
        if current_sequence is not None:
            if isinstance(current_sequence, bool) or not isinstance(current_sequence, int):
                return None
            if sequence < current_sequence or (
                sequence == current_sequence and digest != current_digest
            ):
                return None
        if persist and (
            state is None
            or sequence > int(current_sequence or 0)
        ):
            if not _atomic_write_json(
                self._state_path, {"sequence": sequence, "digest": digest}
            ):
                return None
            if not _atomic_write_json(self._cache_path, payload):
                return None
        self._cached_keys = validated
        return validated

    def _read_state(self) -> tuple[dict[str, Any] | None, bool]:
        try:
            self._state_path.stat()
        except FileNotFoundError:
            return None, True
        except OSError:
            return None, False
        state = self._read_document(self._state_path)
        if (
            state is None
            or set(state) != {"sequence", "digest"}
            or isinstance(state.get("sequence"), bool)
            or not isinstance(state.get("sequence"), int)
            or state["sequence"] < 1
            or not isinstance(state.get("digest"), str)
            or not re.fullmatch(r"[a-f0-9]{64}", state["digest"])
        ):
            return None, False
        return state, True

    @staticmethod
    def _parse_publisher_key(
        raw: Any, registry_sequence: int
    ) -> tuple[str, dict[str, Any]] | None:
        if not isinstance(raw, dict):
            return None
        key_id = raw.get("key_id")
        modulus_hex = raw.get("modulus_hex")
        sequence = raw.get("revoked_at_sequence")
        revoked_at = raw.get("revoked_at_utc")
        status = raw.get("status")
        if (
            not isinstance(key_id, str)
            or not _KEY_ID_RE.fullmatch(key_id)
            or raw.get("algorithm") != "rsa-pkcs1v15-sha256"
            or raw.get("exponent") != 65537
            or raw.get("usages") != ["game-index"]
            or not isinstance(modulus_hex, str)
            or not _HEX_MODULUS_RE.fullmatch(modulus_hex)
            or int(modulus_hex, 16).bit_length() < 2048
            or int(modulus_hex, 16) % 2 == 0
            or not isinstance(status, str)
            or status not in {"active", "revoked"}
        ):
            return None
        if status == "revoked":
            if (
                set(raw)
                not in (
                    {"key_id", "algorithm", "modulus_hex", "exponent", "usages", "status", "revoked_at_sequence", "revoked_at_utc"},
                    {"key_id", "algorithm", "modulus_hex", "exponent", "usages", "status", "revoked_at_sequence", "revoked_at_utc", "reason"},
                )
                or
                isinstance(sequence, bool)
                or not isinstance(sequence, int)
                or not 1 <= sequence <= registry_sequence
                or not isinstance(revoked_at, str)
                or len(revoked_at) < 20
                or len(revoked_at) > 40
                or ("reason" in raw and (not isinstance(raw["reason"], str) or len(raw["reason"]) > 512))
            ):
                return None
        elif set(raw) != {"key_id", "algorithm", "modulus_hex", "exponent", "usages", "status"}:
            return None
        return key_id, {
            "modulus": int(modulus_hex, 16),
            "exponent": 65537,
            "usages": ("game-index",),
            "status": status,
        }


def verify_catalog_signature(
    payload: dict[str, Any], publisher_keys: dict[str, dict[str, Any]] | None
) -> bool:
    signature = payload.get("signature")
    if (
        not isinstance(signature, dict)
        or set(signature) != {"key_id", "value"}
        or not isinstance(signature.get("key_id"), str)
        or not isinstance(signature.get("value"), str)
        or not _KEY_ID_RE.fullmatch(signature["key_id"])
        or not 344 <= len(signature["value"]) <= _MAX_SIGNATURE_TEXT_LENGTH
    ):
        return False
    key = (publisher_keys or {}).get(signature["key_id"])
    if not key or key.get("status") != "active" or "game-index" not in key.get("usages", ()):
        return False
    try:
        signature_bytes = base64.b64decode(signature["value"], validate=True)
    except (ValueError, TypeError):
        return False
    return verify_rsa_sha256_signature(
        canonical_signed_bytes(payload),
        signature_bytes,
        int(key["modulus"]),
        int(key["exponent"]),
    )
