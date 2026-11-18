"""Sign an OpenSourceGameIndex v2 index or trust registry with an offline RSA key."""

from __future__ import annotations

import argparse
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from src.core.catalog.publisher_trust import strict_json_loads  # noqa: E402 - direct script execution
from tools.scripts.build_update_package import _resolve_openssl_bin  # noqa: E402 - direct script execution

_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    unsigned = {key: value for key, value in payload.items() if key != "signature"}
    return json.dumps(
        unsigned,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _validate_document(kind: str, payload: dict[str, Any]) -> None:
    version = payload.get("schema_version")
    if kind == "index":
        revision = payload.get("index_revision")
        if (
            isinstance(version, bool)
            or version != 2
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
            or not isinstance(payload.get("games"), list)
        ):
            raise ValueError("Only OpenSourceGameIndex schema v2 documents can be signed as indexes.")
    elif kind == "registry":
        sequence = payload.get("sequence")
        keys = payload.get("keys")
        if (
            isinstance(version, bool)
            or version != 1
            or isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 1
            or not isinstance(keys, list)
            or not keys
        ):
            raise ValueError("Trust registry must have schema_version 1, a positive sequence, and keys.")
    else:
        raise ValueError("Document kind must be index or registry.")


def sign_document(
    kind: str,
    input_path: str | Path,
    output_path: str | Path,
    key_id: str,
    private_key_path: str | Path,
    openssl_bin: str = "openssl",
) -> None:
    if not _KEY_ID_RE.fullmatch(key_id):
        raise ValueError("Key ID must contain 1-128 letters, digits, dot, underscore, or dash.")
    source_path = Path(input_path).resolve()
    target_path = Path(output_path).resolve()
    private_key = Path(private_key_path).resolve()
    if not source_path.is_file():
        raise FileNotFoundError(f"Input document not found: {source_path}")
    if not private_key.is_file():
        raise FileNotFoundError(f"Private signing key not found: {private_key}")
    if target_path == private_key:
        raise ValueError("Output must not overwrite the private signing key.")
    payload = strict_json_loads(source_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Signed document must be a JSON object.")
    _validate_document(kind, payload)

    canonical = _canonical_bytes(payload)
    signature_path: Path | None = None
    canonical_path: Path | None = None
    temp_output: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".json") as temp_file:
            temp_file.write(canonical)
            canonical_path = Path(temp_file.name)
        with tempfile.NamedTemporaryFile(delete=False, suffix=".sig") as temp_file:
            signature_path = Path(temp_file.name)
        subprocess.run(
            [
                openssl_bin,
                "dgst",
                "-sha256",
                "-sign",
                str(private_key),
                "-out",
                str(signature_path),
                str(canonical_path),
            ],
            check=True,
            capture_output=True,
        )
        signature_value = base64.b64encode(signature_path.read_bytes()).decode("ascii")
        signed = {key: value for key, value in payload.items() if key != "signature"}
        signed["signature"] = {"key_id": key_id, "value": signature_value}
        target_path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            json.dump(signed, temp_file, ensure_ascii=False, indent=2)
            temp_file.write("\n")
            temp_file.flush()
            os.fsync(temp_file.fileno())
            temp_output = Path(temp_file.name)
        os.replace(temp_output, target_path)
        temp_output = None
    finally:
        for path in (canonical_path, signature_path, temp_output):
            if path is not None:
                path.unlink(missing_ok=True)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("kind", choices=("index", "registry"))
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--key-id", required=True)
    parser.add_argument("--private-key", required=True, help="Offline PEM key; never copied to output.")
    parser.add_argument("--openssl-bin", default="openssl")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    openssl = _resolve_openssl_bin(args.openssl_bin, required=True)
    sign_document(
        args.kind,
        args.input,
        args.output,
        args.key_id,
        args.private_key,
        openssl,
    )
    print(f"Signed {args.kind} document with key {args.key_id}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
