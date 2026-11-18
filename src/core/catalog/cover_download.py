"""Bounded public HTTP(S) downloads for explicitly requested game covers."""

from __future__ import annotations

import http.client
import ipaddress
import socket
import time
from urllib.parse import urljoin, urlsplit

_MAX_BYTES = 8 * 1024 * 1024
_MAX_REDIRECTS = 3
_TIMEOUT_SECONDS = 15.0
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}


def _public_address(host: str, port: int) -> str:
    addresses = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    if not addresses:
        raise ValueError("lan_cover_url_invalid")
    resolved = []
    for entry in addresses:
        address = ipaddress.ip_address(entry[4][0].split("%", 1)[0])
        if not address.is_global or address.is_multicast or address.is_reserved:
            raise ValueError("lan_cover_url_invalid")
        resolved.append(str(address))
    return resolved[0]


def download_cover(url: str) -> tuple[str, bytes]:
    """Fetch a public image without following redirects into private networks."""
    deadline = time.monotonic() + _TIMEOUT_SECONDS
    for redirect_count in range(_MAX_REDIRECTS + 1):
        parsed = urlsplit(url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or len(url) > 4096):
            raise ValueError("lan_cover_url_invalid")
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        host = parsed.hostname.encode("idna").decode("ascii")
        address = _public_address(host, port)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("lan_cover_download_failed")
        cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
        conn = cls(host, port=port, timeout=min(5.0, remaining))
        # Pin the validated DNS result while retaining the original TLS hostname.
        conn._create_connection = lambda _address, timeout, source_address=None: socket.create_connection(
            (address, port), timeout=timeout, source_address=source_address
        )
        try:
            path = parsed.path or "/"
            if parsed.query:
                path += "?" + parsed.query
            conn.request("GET", path, headers={"Accept": "image/jpeg,image/png,image/webp,image/gif", "User-Agent": "LANLauncherNG"})
            response = conn.getresponse()
            if response.status in {301, 302, 303, 307, 308}:
                location = response.getheader("Location")
                if not location or redirect_count >= _MAX_REDIRECTS:
                    raise ValueError("lan_cover_download_failed")
                url = urljoin(url, location)
                continue
            if response.status != 200:
                raise ValueError("lan_cover_download_failed")
            mime = response.getheader("Content-Type", "").split(";", 1)[0].strip().lower()
            if mime not in _IMAGE_TYPES:
                raise ValueError("lan_cover_type_invalid")
            content_length = response.getheader("Content-Length")
            if content_length is not None and (not content_length.isdigit() or int(content_length) > _MAX_BYTES):
                raise ValueError("lan_cover_too_large")
            chunks = []
            total = 0
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("lan_cover_download_failed")
                if conn.sock is not None:
                    conn.sock.settimeout(min(5.0, remaining))
                chunk = response.read1(min(65536, _MAX_BYTES + 1 - total))
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_BYTES:
                    raise ValueError("lan_cover_too_large")
                chunks.append(chunk)
            if not total:
                raise ValueError("lan_cover_type_invalid")
            return mime, b"".join(chunks)
        finally:
            conn.close()
    raise ValueError("lan_cover_download_failed")
