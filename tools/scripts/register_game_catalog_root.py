"""Embed a public catalog-root RSA key in LLNG without touching its private key."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from tools.scripts.build_update_package import (  # noqa: E402
    _extract_rsa_public_key_components,
    _resolve_openssl_bin,
    _upsert_public_key_in_registry,
)

_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
_DEFAULT_REGISTRY = "src/core/catalog/publisher_trust.py"


def register_catalog_root(
    public_key_path: str | Path,
    key_id: str,
    registry_path: str | Path = _DEFAULT_REGISTRY,
    openssl_bin: str = "openssl",
) -> int:
    if not _KEY_ID_RE.fullmatch(key_id):
        raise ValueError("Catalog root key ID must contain 1-128 letters, digits, dot, underscore, or dash.")
    public_key = Path(public_key_path).resolve()
    if not public_key.is_file():
        raise FileNotFoundError(f"Public key not found: {public_key}")
    modulus, exponent = _extract_rsa_public_key_components(public_key, openssl_bin)
    bits = modulus.bit_length()
    if not 3072 <= bits <= 4096 or exponent != 65537:
        raise ValueError("Catalog root must be an RSA key of 3072-4096 bits with exponent 65537.")
    registry_file = Path(registry_path).resolve()
    _upsert_public_key_in_registry(
        registry_file,
        key_id,
        modulus,
        exponent,
        registry_name="GAME_CATALOG_ROOT_PUBLIC_KEYS",
    )
    return bits


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-key", required=True, help="Offline catalog-root public PEM file.")
    parser.add_argument("--key-id", required=True, help="Stable catalog root key identifier.")
    parser.add_argument("--registry-file", default=_DEFAULT_REGISTRY)
    parser.add_argument("--openssl-bin", default="openssl")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    openssl = _resolve_openssl_bin(args.openssl_bin, required=True)
    bits = register_catalog_root(
        args.public_key,
        args.key_id,
        args.registry_file,
        openssl,
    )
    print(f"Embedded catalog root {args.key_id} ({bits}-bit RSA) from public key only.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
