"""Bounded cover downloads and image conversion for server metadata."""

import shutil
import socket
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from src.core.catalog.cover_download import _MAX_BYTES, _public_address, download_cover
from src.core.config.loader import AppConfig
from src.core.service.app import Application
from src.core.service.settings_store import UserSettings


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in {"/redirect", "/private"}:
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1/secret" if self.path == "/private" else "/image")
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html" if self.path == "/html" else "image/png")
        if self.path == "/large":
            self.send_header("Content-Length", str(_MAX_BYTES + 1))
        self.end_headers()
        if self.path != "/large":
            self.wfile.write(b"fake image bytes")

    def log_message(self, *_args):
        pass


class CoverDownloadTests(unittest.TestCase):
    def test_http_download_redirect_type_and_size(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://example.org:{server.server_port}"
            with patch("src.core.catalog.cover_download._public_address", return_value="127.0.0.1"):
                self.assertEqual(download_cover(url + "/redirect"), ("image/png", b"fake image bytes"))
                with self.assertRaisesRegex(ValueError, "lan_cover_type_invalid"):
                    download_cover(url + "/html")
                with self.assertRaisesRegex(ValueError, "lan_cover_too_large"):
                    download_cover(url + "/large")
            def pin(host, port):
                if host == "127.0.0.1":
                    raise ValueError("lan_cover_url_invalid")
                return "127.0.0.1"
            with patch("src.core.catalog.cover_download._public_address", side_effect=pin):
                with self.assertRaisesRegex(ValueError, "lan_cover_url_invalid"):
                    download_cover(url + "/private")
        finally:
            server.shutdown()
            server.server_close()
            thread.join()

    def test_rejects_private_and_mixed_dns_answers_and_credentials(self):
        def address(ip):
            return (socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 80))
        with patch("socket.getaddrinfo", return_value=[address("8.8.8.8"), address("127.0.0.1")]):
            with self.assertRaisesRegex(ValueError, "lan_cover_url_invalid"):
                _public_address("example.org", 80)
        with patch("socket.getaddrinfo", return_value=[address("224.0.0.1")]):
            with self.assertRaisesRegex(ValueError, "lan_cover_url_invalid"):
                _public_address("example.org", 80)
        for url in ("file:///tmp/a", "http://user:password@example.org/a", "http://127.0.0.1/a"):
            with self.assertRaises(ValueError):
                download_cover(url)

    def test_local_action_requires_server_and_returns_bounded_data(self):
        app = Application(AppConfig(bind_port=0))
        self.addCleanup(app._server.server_close)
        self.assertEqual(app._lan_game_share_update({"action": "download_cover"})["message"], "server_mode_required")
        app._state.user_settings = UserSettings(
            nickname="Tester", theme="dark", log_level="WARNING", auto_start_sync=True,
            library_path_initialized=True, windows_game_drive_letter="D",
            linux_install_path="library", lan_mode="server",
        )
        with patch("src.core.service.app.download_cover", return_value=("image/png", b"abc")):
            result = app._lan_game_share_update({"action": "download_cover", "url": "https://example.org/a"})
        self.assertEqual(result["data_url"], "data:image/png;base64,YWJj")

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_editor_stages_cover_only_after_success_and_ignores_stale_response(self):
        source = Path("src/frontend/app/app.js").read_text(encoding="utf-8")
        start = source.index("  async function downloadServerCover()")
        end = source.index("  async function onLocalGameSave()", start)
        script = r'''
const assert = require("assert");
let downloadedServerCover = "", serverCoverGeneration = 0, resolveRequest, payload;
const state = {serverFolderEditing: {}};
const el = {serverCoverDownloadBtn: {disabled: false}, localGameSaveBtn: {disabled: false}, serverCoverDownloadStatus: {textContent: ""}, serverCoverUrl: {value: " https://example.org/image "}, localGameImage: {value: "old"}};
const t = key => key;
let request = Promise.resolve({result: {data_url: "input"}});
const apiPost = async (_path, data) => {payload = data; return await request;};
const convertServerCover = async data => data === "input" ? "converted" : Promise.reject(Error("bad"));
''' + source[start:end] + r'''
(async () => {
  await downloadServerCover();
  assert.equal(payload.url, "https://example.org/image");
  assert.equal(downloadedServerCover, "converted");
  assert.equal(el.localGameImage.value, "");
  request = Promise.resolve({result: {data_url: "bad"}});
  await downloadServerCover();
  assert.equal(downloadedServerCover, "");
  assert.equal(el.serverCoverDownloadStatus.textContent, "game.server_cover_failed");
  request = new Promise(resolve => {resolveRequest = resolve;});
  const pending = downloadServerCover();
  serverCoverGeneration += 1;
  resolveRequest({result: {data_url: "input"}});
  await pending;
  assert.equal(downloadedServerCover, "");
})().catch(e => {console.error(e); process.exit(1);});
'''
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)

    @unittest.skipUnless(shutil.which("node"), "Node.js required")
    def test_browser_scales_cover_and_closes_bitmap(self):
        source = Path("src/frontend/app/app.js").read_text(encoding="utf-8")
        start = source.index("  async function convertServerCover(dataUrl)")
        end = source.index("  async function downloadServerCover()", start)
        script = r'''
const assert = require("assert");
let closed = false, canvas;
const fetch = async () => ({blob: async () => ({})});
const createImageBitmap = async () => ({width: 3200, height: 800, close() {closed = true;}});
const document = {createElement: () => canvas = {width: 0, height: 0, getContext: () => ({fillRect(){}, drawImage(){}}), toDataURL: (type, quality) => {assert.equal(type, "image/jpeg"); assert.equal(quality, .85); return "data:image/jpeg;base64,AAAA";}}};
''' + source[start:end] + r'''
(async () => {assert.equal(await convertServerCover("data:image/png;base64,AAAA"), "data:image/jpeg;base64,AAAA"); assert.equal(canvas.width, 1600); assert.equal(canvas.height, 400); assert(closed);})().catch(e => {console.error(e); process.exit(1);});
'''
        subprocess.run(["node", "-e", script], check=True, capture_output=True, text=True)
