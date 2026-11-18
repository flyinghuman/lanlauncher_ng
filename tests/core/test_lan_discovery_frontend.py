"""Exercise the client discovery UI logic without a browser dependency."""

from __future__ import annotations

import shutil
import subprocess
import unittest
from pathlib import Path


@unittest.skipUnless(shutil.which("node"), "Node.js is needed for frontend logic tests")
class LanDiscoveryFrontendTests(unittest.TestCase):
    def test_search_results_errors_and_role_changes(self) -> None:
        source = Path("src/frontend/app/app.js").read_text(encoding="utf-8")
        start = source.index("  let lanDiscoveryGeneration = 0;")
        end = source.index("  async function onLanGameShareToggle", start)
        script = r'''
const assert = require("assert");
const state = {locale: "en", settings: {lan_mode: "client"}};
let role = "client", calls = [], response;
const currentLanMode = () => role;
const t = (key) => key;
const document = {createElement: () => ({textContent: ""})};
const el = {
  lanModeSelect: {get value() { return role; }},
  lanDiscoverySection: {hidden: false},
  lanDiscoveryScan: {disabled: false},
  lanDiscoveryAddress: {value: " 192.168.1.7 "},
  lanDiscoveryStatus: {textContent: ""},
  lanServerSelect: {value: "0", disabled: false, items: [], replaceChildren() {this.items = [];}, append(item) {this.items.push(item);}},
  lanPairCode: {value: "1234"}, lanPairConnect: {disabled: false}, lanPairStatus: {textContent: ""},
  lanPairServerSection: {hidden: true}, lanPairBegin: {disabled: false}, lanPairRenew: {disabled: false}, lanPairServerStatus: {textContent: ""},
};
const apiPost = async (path, payload) => { calls.push({path, payload}); return await response; };
''' + source[start:end] + r'''
(async () => {
  response = Promise.resolve({result: {servers: [{name: "<server>", address: "192.168.1.7", device_id: "ABC"}]}});
  await scanLanServers();
  assert.equal(calls[0].payload.address, "192.168.1.7");
  assert.equal(calls[0].payload.action, "discover_servers");
  assert.equal(el.lanServerSelect.items[0].textContent, "<server> — 192.168.1.7 (ABC)");
  assert.equal(el.lanDiscoveryStatus.textContent, "settings.lan_discovery_found");
  response = Promise.resolve({result: {}});
  await connectLanServer();
  assert.equal(calls[1].payload.action, "pair_server");
  assert.equal(calls[1].payload.device_id, "ABC");
  assert.equal(calls[1].payload.code, "1234");
  assert.equal(el.lanPairCode.value, "");
  assert.equal(el.lanPairStatus.textContent, "settings.lan_pair_success");
  el.lanPairCode.value = "abc";
  await connectLanServer();
  assert.equal(el.lanPairStatus.textContent, "settings.lan_pair_invalid");
  response = Promise.resolve({result: {servers: []}});
  await scanLanServers();
  assert.equal(el.lanDiscoveryStatus.textContent, "settings.lan_discovery_empty");
  response = Promise.reject(new Error("network"));
  await scanLanServers();
  assert.equal(el.lanDiscoveryStatus.textContent, "settings.lan_discovery_failed");
  state.settings.lan_mode = "server";
  await scanLanServers();
  assert.equal(el.lanDiscoveryStatus.textContent, "settings.lan_discovery_save_first");
  state.settings.lan_mode = "client";
  let resolve;
  response = new Promise(r => {resolve = r;});
  const pending = scanLanServers();
  role = "server";
  renderLanDiscoveryVisibility();
  resolve({result: {servers: [{name: "stale"}]}});
  await pending;
  assert.equal(el.lanDiscoverySection.hidden, true);
  assert.equal(el.lanServerSelect.items.length, 0);
  assert.equal(el.lanDiscoveryScan.disabled, false);
  state.settings.lan_mode = "server";
  response = Promise.resolve({result: {code: "0042", expires_in: 259200}});
  await beginLanPairing();
  assert.equal(calls[calls.length - 1].payload.action, "begin_pairing");
  assert(el.lanPairServerStatus.textContent.startsWith("settings.lan_pair_show_code: 0042 — settings.lan_pair_valid_until:"));
  response = Promise.resolve({result: {code: "5678", expires_in: 259200}});
  await renewLanPairing();
  assert.equal(calls[calls.length - 1].payload.action, "renew_pairing");
  assert(el.lanPairServerStatus.textContent.startsWith("settings.lan_pair_show_code: 5678 — settings.lan_pair_valid_until:"));
  assert.equal(el.lanPairRenew.disabled, false);
  renderLanDiscoveryVisibility();
  assert.equal(el.lanPairServerStatus.textContent, "");
})().catch(error => {console.error(error); process.exit(1);});
'''
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
