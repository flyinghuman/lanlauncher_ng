#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"
if [[ "$MODE" != "lan" && "$MODE" != "internet" ]]; then
  echo "invalid_network_mode" >&2
  exit 1
fi

if ! command -v iptables >/dev/null 2>&1; then
  echo "iptables_not_found" >&2
  exit 1
fi

CHAIN="LLNG_RESILIO_LAN"
TARGET_UID="${SUDO_UID:-$(id -u)}"

remove_rules() {
  while iptables -C OUTPUT -m owner --uid-owner "$TARGET_UID" -j "$CHAIN" 2>/dev/null; do
    iptables -D OUTPUT -m owner --uid-owner "$TARGET_UID" -j "$CHAIN"
  done
  iptables -F "$CHAIN" 2>/dev/null || true
  iptables -X "$CHAIN" 2>/dev/null || true
}

if [[ "$MODE" == "internet" ]]; then
  remove_rules
  echo "internet_mode_rules_removed"
  exit 0
fi

# LAN mode for Linux is enforced via a dedicated OUTPUT chain scoped to the launcher user UID.
remove_rules
iptables -N "$CHAIN"
iptables -A "$CHAIN" -d 127.0.0.0/8 -j RETURN
iptables -A "$CHAIN" -d 10.0.0.0/8 -j RETURN
iptables -A "$CHAIN" -d 172.16.0.0/12 -j RETURN
iptables -A "$CHAIN" -d 192.168.0.0/16 -j RETURN
iptables -A "$CHAIN" -d 169.254.0.0/16 -j RETURN
iptables -A "$CHAIN" -j REJECT
iptables -A OUTPUT -m owner --uid-owner "$TARGET_UID" -j "$CHAIN"
echo "lan_mode_rules_applied"
