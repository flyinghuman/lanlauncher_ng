"""Bounded UDP discovery and explicit pairing for LANLauncherNG servers."""

from __future__ import annotations

import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import secrets
import socket
import threading
import tempfile
import time
from collections.abc import Callable
from pathlib import Path

DISCOVERY_PORT = 28384
_MAX_PACKET = 8192
_MAX_CAPABILITIES = 6144
_MAX_CLIENT_PEER_ADDRS = 4
_MAX_ROSTER_PEER_ADDRS = 64
_ID = re.compile(r"^(?:[A-Z2-7]{7}-){7}[A-Z2-7]{7}$")
_QUIC_ADDR = re.compile(r"^quic/([^/:]+):([0-9]{1,5})$")


def _peer_address(value: object, *, allow_wildcard: bool = False) -> str | None:
    if not isinstance(value, str):
        return None
    match = _QUIC_ADDR.fullmatch(value)
    if match is None:
        return None
    try:
        address = ipaddress.ip_address(match.group(1))
        port = int(match.group(2))
    except ValueError:
        return None
    if address.version != 4 or not 1 <= port <= 65535:
        return None
    if address.is_unspecified:
        return value if allow_wildcard else None
    if address.is_multicast or address.is_reserved:
        return None
    return f"quic/{address}:{port}"


def _request_peer_addresses(request: dict, observed_address: str | None) -> list[str]:
    value = request.get("peer_addrs", [])
    if not isinstance(value, list) or len(value) > _MAX_CLIENT_PEER_ADDRS:
        raise ValueError("lan_pair_peer_addresses_invalid")
    observed = None
    if observed_address:
        try:
            parsed = ipaddress.ip_address(observed_address)
            if parsed.version == 4 and not parsed.is_multicast and not parsed.is_unspecified:
                observed = str(parsed)
        except ValueError:
            pass
    result: list[str] = []
    for item in value:
        address = _peer_address(item, allow_wildcard=True)
        if address is None:
            raise ValueError("lan_pair_peer_addresses_invalid")
        if address.startswith("quic/0.0.0.0:"):
            if observed is None:
                continue
            address = address.replace("quic/0.0.0.0:", f"quic/{observed}:", 1)
        if address not in result:
            result.append(address)
    return result


def paired_peer_addresses(capabilities: dict, server_address: str) -> list[str]:
    """Resolve owner endpoints and validate its authenticated paired-client roster."""
    try:
        owner_ip = ipaddress.ip_address(server_address)
    except ValueError as exc:
        raise ValueError("lan_pair_address_invalid") from exc
    if owner_ip.version != 4 or owner_ip.is_unspecified or owner_ip.is_multicast:
        raise ValueError("lan_pair_address_invalid")
    owner_values = capabilities.get("peer_addrs", [])
    known_values = capabilities.get("known_peer_addrs", [])
    if (
        not isinstance(owner_values, list)
        or len(owner_values) > _MAX_CLIENT_PEER_ADDRS
        or not isinstance(known_values, list)
        or len(known_values) > _MAX_ROSTER_PEER_ADDRS
    ):
        raise ValueError("lan_pair_peer_addresses_invalid")
    result: list[str] = []
    for value in owner_values:
        address = _peer_address(value, allow_wildcard=True)
        if address is None:
            raise ValueError("lan_pair_peer_addresses_invalid")
        if address.startswith("quic/0.0.0.0:"):
            address = address.replace("quic/0.0.0.0:", f"quic/{owner_ip}:", 1)
        if address not in result:
            result.append(address)
    for value in known_values:
        address = _peer_address(value)
        if address is None:
            raise ValueError("lan_pair_peer_addresses_invalid")
        if address not in result:
            result.append(address)
    return result[:_MAX_ROSTER_PEER_ADDRS]


def _pair_proof(
    code: str,
    kind: str,
    nonce: str,
    server_id: str,
    client_id: str,
    capabilities: dict | None = None,
) -> str:
    fields = [kind, nonce, server_id, client_id]
    if capabilities is not None:
        fields.append(json.dumps(capabilities, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False))
    message = "\n".join(fields).encode("ascii")
    return hmac.new(code.encode("ascii"), message, hashlib.sha256).hexdigest()


PAIRING_LIFETIME_SECONDS = 3 * 24 * 60 * 60
_PAIRING_LOCKOUT_SECONDS = 60


class LanPairing:
    """Persist a reusable, expiring LAN-party code and bound online guesses."""

    def __init__(self, server_id: Callable[[], str], approve: Callable[[str], bool | dict], *,
                 clock=time.time, storage: Path | None = None):
        self._server_id = server_id
        self._approve = approve
        self._clock = clock
        self._storage = storage
        self._lock = threading.Lock()
        self._code = ""
        self._expires = 0.0
        self._attempts = 0
        self._locked_until = 0.0
        self._failed_proofs: set[tuple[str, str]] = set()
        self._peers: dict[str, list[str]] = {}
        self._load()

    def _load(self) -> None:
        if self._storage is None:
            return
        try:
            data = json.loads(self._storage.read_text(encoding="utf-8"))
            code, expires = data["code"], float(data["expires_at"])
            if isinstance(code, str) and re.fullmatch(r"[0-9]{4}", code) and self._clock() < expires <= self._clock() + PAIRING_LIFETIME_SECONDS:
                self._code, self._expires = code, expires
            peers = data.get("peers", {})
            if isinstance(peers, dict):
                for client_id, addresses in peers.items():
                    if not isinstance(client_id, str) or not _ID.fullmatch(client_id):
                        continue
                    if not isinstance(addresses, list):
                        continue
                    safe = [
                        address
                        for item in addresses[:_MAX_CLIENT_PEER_ADDRS]
                        if (address := _peer_address(item)) is not None
                    ]
                    if safe:
                        self._peers[client_id] = list(dict.fromkeys(safe))
        except (OSError, ValueError, TypeError, KeyError, OverflowError):
            pass

    def _save(self, code: str, expires: float) -> None:
        if self._storage is None:
            return
        self._storage.parent.mkdir(parents=True, exist_ok=True)
        fd, name = tempfile.mkstemp(prefix=".lan-pairing-", dir=self._storage.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(
                    {"code": code, "expires_at": expires, "peers": self._peers},
                    handle,
                    separators=(",", ":"),
                )
            os.replace(name, self._storage)
        finally:
            Path(name).unlink(missing_ok=True)

    def begin(self) -> str:
        with self._lock:
            now = self._clock()
            if self._code and now < self._expires:
                return self._code
            return self._renew_locked(now)

    def renew(self) -> str:
        """Replace the current code immediately and restart its three-day lifetime."""
        with self._lock:
            return self._renew_locked(self._clock())

    def _renew_locked(self, now: float) -> str:
        previous_code = self._code if now < self._expires else ""
        if previous_code:
            candidate = secrets.randbelow(9999)
            previous_number = int(previous_code)
            if candidate >= previous_number:
                candidate += 1
        else:
            candidate = secrets.randbelow(10000)
        code = f"{candidate:04d}"
        expires = now + PAIRING_LIFETIME_SECONDS
        self._save(code, expires)
        self._code, self._expires = code, expires
        self._attempts = 0
        self._locked_until = 0
        self._failed_proofs.clear()
        return code

    def remaining(self) -> int:
        with self._lock:
            return max(0, math.ceil(self._expires - self._clock())) if self._code else 0

    def accept(self, request: dict, *, observed_address: str | None = None) -> dict | None:
        nonce, server_id, client_id, proof = (request.get(key) for key in ("nonce", "server_id", "client_id", "proof"))
        if not all(isinstance(value, str) for value in (nonce, server_id, client_id, proof)):
            return None
        if not re.fullmatch(r"[a-f0-9]{32}", nonce) or not _ID.fullmatch(server_id) or not _ID.fullmatch(client_id) or server_id == client_id or not re.fullmatch(r"[a-f0-9]{64}", proof):
            return None
        try:
            peer_addrs = _request_peer_addresses(request, observed_address)
            request_capabilities = (
                {"peer_addrs": request.get("peer_addrs", [])}
                if "peer_addrs" in request
                else None
            )
        except ValueError:
            return None
        with self._lock:
            now = self._clock()
            if not self._code or now >= self._expires or now < self._locked_until:
                return None
            if self._locked_until:
                self._locked_until = 0
                self._attempts = 0
                self._failed_proofs.clear()
            try:
                if self._server_id() != server_id:
                    return None
            except Exception:
                return None
            if not hmac.compare_digest(
                proof,
                _pair_proof(
                    self._code,
                    "request",
                    nonce,
                    server_id,
                    client_id,
                    request_capabilities,
                ),
            ):
                # UDP retries of one failed request count as one attempt.
                attempt = (nonce, proof)
                if attempt not in self._failed_proofs:
                    self._failed_proofs.add(attempt)
                    self._attempts += 1
                    if self._attempts >= 5:
                        self._locked_until = now + _PAIRING_LOCKOUT_SECONDS
                return None
            try:
                approval = self._approve(client_id)
                if isinstance(approval, dict):
                    capabilities = dict(approval)
                elif approval:
                    capabilities = None
                else:
                    return None
            except Exception:
                return None
            if "peer_addrs" in request:
                if peer_addrs:
                    self._peers[client_id] = peer_addrs
                else:
                    self._peers.pop(client_id, None)
                self._save(self._code, self._expires)
            if capabilities is not None:
                known_peer_addrs = [
                    address
                    for peer_id, addresses in self._peers.items()
                    if peer_id != client_id
                    for address in addresses
                ][-_MAX_ROSTER_PEER_ADDRS:]
                if known_peer_addrs:
                    capabilities["known_peer_addrs"] = list(
                        dict.fromkeys(known_peer_addrs)
                    )
            response = {"type": "llng-paired-v1", "nonce": nonce, "server_id": server_id,
                        "client_id": client_id}
            if capabilities is not None:
                try:
                    encoded = json.dumps(capabilities, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode("ascii")
                except (TypeError, ValueError, UnicodeError):
                    return None
                if len(encoded) > _MAX_CAPABILITIES:
                    return None
                response["capabilities"] = capabilities
            response["proof"] = _pair_proof(self._code, "response", nonce, server_id, client_id, capabilities)
            return response


def pair_server_capabilities(
    address: str,
    server_id: str,
    client_id: str,
    code: str,
    *,
    port: int = DISCOVERY_PORT,
    timeout: float = 3.0,
    peer_addrs: list[str] | None = None,
) -> dict | None:
    """Pair with a server and return its code-authenticated capability payload."""
    target = ipaddress.ip_address(address)
    if target.version != 4 or target.is_multicast or target.is_unspecified or str(target) == "255.255.255.255":
        raise ValueError("lan_pair_address_invalid")
    if not _ID.fullmatch(server_id) or not _ID.fullmatch(client_id) or server_id == client_id or not re.fullmatch(r"[0-9]{4}", code):
        raise ValueError("lan_pair_invalid")
    nonce = secrets.token_hex(16)
    raw_peer_addrs = list(dict.fromkeys(peer_addrs or []))
    if len(raw_peer_addrs) > _MAX_CLIENT_PEER_ADDRS or any(
        _peer_address(value, allow_wildcard=True) is None for value in raw_peer_addrs
    ):
        raise ValueError("lan_pair_peer_addresses_invalid")
    request_capabilities = {"peer_addrs": raw_peer_addrs} if peer_addrs is not None else None
    request = {"type": "llng-pair-v1", "nonce": nonce, "server_id": server_id, "client_id": client_id,
               "proof": _pair_proof(code, "request", nonce, server_id, client_id, request_capabilities)}
    if peer_addrs is not None:
        request["peer_addrs"] = raw_peer_addrs
    deadline = time.monotonic() + max(0.1, min(timeout, 5.0))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.connect((str(target), port))
        while time.monotonic() < deadline:
            sock.send(json.dumps(request).encode("utf-8"))
            sock.settimeout(min(0.5, max(0.01, deadline - time.monotonic())))
            try:
                raw = sock.recv(_MAX_PACKET + 1)
                if len(raw) > _MAX_PACKET:
                    continue
                reply = json.loads(raw.decode("utf-8"))
            except socket.timeout:
                continue
            except (ValueError, UnicodeError):
                continue
            if not isinstance(reply, dict) or reply.get("type") != "llng-paired-v1" or reply.get("nonce") != nonce:
                continue
            if reply.get("server_id") != server_id or reply.get("client_id") != client_id:
                continue
            capabilities = reply.get("capabilities")
            if capabilities is not None and not isinstance(capabilities, dict):
                continue
            try:
                expected = _pair_proof(code, "response", nonce, server_id, client_id, capabilities)
            except (TypeError, ValueError, UnicodeError):
                continue
            if isinstance(reply.get("proof"), str) and hmac.compare_digest(reply["proof"], expected):
                return capabilities or {}
    return None


def pair_server(address: str, server_id: str, client_id: str, code: str, *, port: int = DISCOVERY_PORT, timeout: float = 3.0) -> bool:
    return pair_server_capabilities(address, server_id, client_id, code, port=port, timeout=timeout) is not None


class LanDiscoveryServer:
    def __init__(
        self,
        info: Callable[[], dict | None],
        *,
        pairing: LanPairing | None = None,
        host: str = "0.0.0.0",
        port: int = DISCOVERY_PORT,
    ):
        self._info = info
        self._pairing = pairing
        self._socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self._socket.bind((host, port))
        except OSError:
            self._socket.close()
            raise
        self._socket.settimeout(0.25)
        self.port = int(self._socket.getsockname()[1])
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="lan-discovery"
        )

    def start(self) -> None:
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2)
        self._socket.close()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                packet, address = self._socket.recvfrom(_MAX_PACKET + 1)
            except socket.timeout:
                continue
            except OSError:
                return
            if len(packet) > _MAX_PACKET:
                continue
            try:
                request = json.loads(packet.decode("utf-8"))
                if not isinstance(request, dict):
                    continue
                if request.get("type") == "llng-pair-v1":
                    if self._pairing is not None:
                        response = self._pairing.accept(
                            request, observed_address=address[0]
                        )
                        if response is not None:
                            self._socket.sendto(
                                json.dumps(response).encode("utf-8"), address
                            )
                    continue
                if request.get("type") != "llng-discover-v1":
                    continue
                nonce = request.get("nonce")
                if not isinstance(nonce, str) or not re.fullmatch(
                    r"[a-f0-9]{32}", nonce
                ):
                    continue
                try:
                    info = self._info()
                except Exception:
                    continue
                if not isinstance(info, dict) or not _ID.fullmatch(
                    str(info.get("device_id", ""))
                ):
                    continue
                response = {
                    "type": "llng-server-v1",
                    "nonce": nonce,
                    "name": str(info.get("name") or "LANLauncherNG")[:80],
                    "device_id": info["device_id"],
                    "catalog_folder_id": "locallansync",
                    "tcp_port": info.get("tcp_port", 22000),
                }
                if type(response["tcp_port"]) is not int or not 1 <= response["tcp_port"] <= 65535:
                    continue
                self._socket.sendto(json.dumps(response).encode("utf-8"), address)
            except (ValueError, UnicodeError, OSError):
                continue


def discover_servers(
    *, target: str = "255.255.255.255", port: int = DISCOVERY_PORT, timeout: float = 1.0
) -> list[dict]:
    """Discover servers via IPv4 broadcast or a manually supplied IPv4 address."""
    address = ipaddress.ip_address(target)
    if address.version != 4:
        raise ValueError("lan_discovery_address_invalid")
    nonce = secrets.token_hex(16)
    request = json.dumps({"type": "llng-discover-v1", "nonce": nonce}).encode("utf-8")
    found: dict[tuple[str, str], dict] = {}
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.bind(("0.0.0.0", 0))
        sock.sendto(request, (str(address), port))
        deadline = time.monotonic() + max(0.1, min(timeout, 3.0))
        while time.monotonic() < deadline:
            sock.settimeout(max(0.01, deadline - time.monotonic()))
            try:
                packet, sender = sock.recvfrom(_MAX_PACKET + 1)
            except socket.timeout:
                break
            if len(packet) > _MAX_PACKET:
                continue
            if sender[1] != port:
                continue
            try:
                item = json.loads(packet.decode("utf-8"))
                if (
                    not isinstance(item, dict)
                    or item.get("type") != "llng-server-v1"
                    or item.get("nonce") != nonce
                ):
                    continue
                device_id = item.get("device_id")
                if (
                    not isinstance(device_id, str)
                    or not _ID.fullmatch(device_id)
                    or item.get("catalog_folder_id") != "locallansync"
                ):
                    continue
                name = item.get("name")
                tcp_port = item.get("tcp_port", 22000)
                if not isinstance(name, str) or len(name) > 80 or type(tcp_port) is not int or not 1 <= tcp_port <= 65535:
                    continue
                found[(device_id, sender[0])] = {
                    "name": name,
                    "device_id": device_id,
                    "address": sender[0],
                    "catalog_folder_id": "locallansync",
                    "tcp_port": tcp_port,
                }
            except (ValueError, UnicodeError):
                continue
    return sorted(
        found.values(), key=lambda item: (item["name"].casefold(), item["address"])
    )
