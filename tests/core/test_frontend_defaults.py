"""Frontend default state regression tests."""

from __future__ import annotations

import json
import unittest
from pathlib import Path


class FrontendDefaultsTests(unittest.TestCase):
    def test_first_run_wizard_explains_distribution_modes(self) -> None:
        app_js = Path("src/frontend/app/app.js").read_text(encoding="utf-8")
        html = Path("src/frontend/app/index.html").read_text(encoding="utf-8")
        css = Path("src/frontend/styles/main.css").read_text(encoding="utf-8")
        for element_id in (
            "wizard-provider-guidance-title",
            "wizard-provider-global",
            "wizard-provider-legacy",
            "wizard-provider-lan",
        ):
            self.assertIn(f'id="{element_id}"', html)
        self.assertIn('t("wizard.provider_global")', app_js)
        self.assertIn('t("wizard.provider_legacy")', app_js)
        self.assertIn('t("wizard.provider_lan")', app_js)
        self.assertIn(".welcome-wizard-modal", css)
        self.assertIn("overflow: auto;", css)

    def test_default_locale_and_view_mode(self) -> None:
        app_js = Path("src/frontend/app/app.js").read_text(encoding="utf-8")
        html = Path("src/frontend/app/index.html").read_text(encoding="utf-8")
        css = Path("src/frontend/styles/main.css").read_text(encoding="utf-8")
        self.assertIn('locale: localStorage.getItem("llng.locale") || "de"', app_js)
        self.assertIn(
            'viewMode: localStorage.getItem("llng.view_mode") || "grid"',
            app_js,
        )
        self.assertIn(
            'gridTileSize: localStorage.getItem("llng.grid_tile_size") || "medium"',
            app_js,
        )
        self.assertIn(
            'topTrafficMode: localStorage.getItem("llng.top_traffic_mode") || "bar"',
            app_js,
        )
        self.assertIn("function updateCatalogGridSizing()", app_js)
        self.assertIn("function normalizeGridTileSize(value)", app_js)
        self.assertIn("const GRID_TILE_SIZE_PRESETS =", app_js)
        self.assertIn("el.deleteGameBtn.disabled = !canUseGameActions;", app_js)
        self.assertIn("catalogRetryTimer: 0", app_js)
        self.assertIn("catalogLoadAttempts: 0", app_js)
        self.assertIn("catalogLoaded: false", app_js)
        self.assertIn("catalogSyncRefreshTimer: 0", app_js)
        self.assertIn('"ui.catalog_loading",', app_js)
        self.assertIn('"Loading catalog...",', app_js)
        self.assertIn("state.catalogLoadAttempts >= 10", app_js)
        self.assertIn("state.catalogLoaded = true", app_js)
        self.assertIn('linux_install_path: "/media/library"', app_js)
        self.assertIn("sync_only_mode: false", app_js)
        self.assertIn('effective_library_path: "/media/library"', app_js)
        self.assertIn("function isReadyToInstall(syncState)", app_js)
        self.assertIn('t("game.fully_synced", "Fully synced")', app_js)
        self.assertIn('"settings.sync_only_mode"', app_js)
        self.assertIn("function setSettingsDirty(dirty)", app_js)
        self.assertIn('"input",\n      markGeneralSettingsDirty,', app_js)
        self.assertIn('"change",\n      markGeneralSettingsDirty,', app_js)
        self.assertIn("serverRolePreview: true", app_js)
        self.assertIn('id="lan-server-settings-section"', html)
        self.assertIn('id="lan-server-assets-list"', html)
        self.assertIn('id="lan-pair-renew"', html)
        self.assertLess(
            html.index('id="status-lan-games-section"'),
            html.index('id="lan-server-settings-section"'),
        )
        self.assertIn("grid-area: lan-server;", css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", css)
        self.assertIn('apiPost("/settings/lan-server"', app_js)
        self.assertIn('state.launcherSite?.managed_by_lan_server', app_js)
        self.assertIn('item?.install_state || "").toLowerCase() === "installed"', app_js)
        self.assertIn("#lan-server-settings-save.is-dirty", css)
        self.assertIn('"?role=server"', app_js)
        self.assertIn('inventory.message === "loading"', app_js)
        self.assertIn("backendReady: false", app_js)
        self.assertIn("function updateStartupScreen()", app_js)
        self.assertIn('el.wizardStorageInput.placeholder = "/media/library";', app_js)
        self.assertIn("function sendShutdownKeepaliveOnWindowClose()", app_js)
        self.assertIn('fetch("/app/shutdown"', app_js)
        self.assertIn("keepalive: true", app_js)
        self.assertNotIn('window.location.replace("about:blank")', app_js)
        self.assertNotIn('window.open("", "_self")', app_js)
        self.assertIn('window.addEventListener("pagehide", () => {', app_js)
        self.assertIn('window.addEventListener("beforeunload", () => {', app_js)
        self.assertIn("async function waitForBackendReady(", app_js)
        self.assertIn('const raw = await fetch("/health"', app_js)
        self.assertIn(
            'String(nextSettings.platform || "").toLowerCase() === "unknown"',
            app_js,
        )
        self.assertIn("if (!state.backendReady) {", app_js)
        self.assertIn("await waitForBackendReady();", app_js)
        self.assertIn(
            'state.settings.platform === "windows" ? "D" : "/media/library";',
            app_js,
        )
        self.assertIn(
            "progress_percent: Number(previousSync?.progress_percent || 0)",
            app_js,
        )
        self.assertIn(
            "await loadSelectedGameSyncStatus();",
            app_js,
        )
        self.assertIn(
            "progress bar does not jump to 0% between refresh ticks",
            app_js,
        )
        self.assertIn(
            'topTrafficToggle: document.getElementById("top-traffic-toggle")',
            app_js,
        )
        self.assertIn(
            'topProviderBadges: document.getElementById("top-provider-badges")',
            app_js,
        )
        self.assertIn(
            'activeStatusProvider:\n      localStorage.getItem("llng.active_status_provider") || "resilio"',
            app_js,
        )
        self.assertIn("function updateTopbarUpdateState()", app_js)
        self.assertIn("function updateTopbarTrafficSizing()", app_js)
        self.assertIn("--top-traffic-basis", app_js)
        self.assertIn("--top-traffic-max-width", app_js)
        self.assertIn('const minWidth = state.updateAvailable ? 148 : 160;', app_js)
        self.assertIn('const maxWidth = state.updateAvailable ? 184 : 196;', app_js)
        self.assertIn("Keep every series on the same x coordinate", app_js)
        self.assertIn('const barX = groupX + Math.max(0, (groupWidth - barWidth) / 2);', app_js)
        self.assertIn("topbar-update-available", app_js)
        self.assertNotIn('topTrafficTitle: document.getElementById("top-traffic-title")', app_js)
        self.assertNotIn('topTrafficMode: document.getElementById("top-traffic-mode")', app_js)
        self.assertNotIn('topTrafficSummary: document.getElementById("top-traffic-summary")', app_js)
        self.assertIn("topTrafficHistory: []", app_js)
        self.assertIn("function renderTopTrafficChart()", app_js)
        self.assertIn('el.topTrafficToggle.setAttribute("aria-label", trafficHintText());', app_js)
        self.assertIn('el.topTrafficInfo.setAttribute(', app_js)
        self.assertNotIn("updateTopTrafficInfoPosition", app_js)
        self.assertIn('topTrafficInfo: document.getElementById("top-traffic-info")', app_js)
        self.assertIn(
            'topTrafficInfoHint: document.getElementById("top-traffic-info-hint")',
            app_js,
        )
        self.assertIn(
            'topTrafficInfoDownloadLabel: document.getElementById(',
            app_js,
        )
        self.assertIn("ResizeObserver", app_js)
        self.assertIn("TOP_TRAFFIC_HISTORY_LIMIT = 2048", app_js)
        self.assertIn('settings.extra_sync_update_images', app_js)
        self.assertIn('gridSizeSelect: document.getElementById("grid-size-select")', app_js)
        self.assertIn('labelGridSize: document.getElementById("label-grid-size")', app_js)
        self.assertIn('activeTab: localStorage.getItem("llng.active_tab") || "home"', app_js)
        self.assertIn(
            'activeProviderTab:\n      localStorage.getItem("llng.active_provider_tab") || "ouisync"',
            app_js,
        )
        self.assertIn('data-provider-tab="ouisync"', html)
        self.assertIn('id="ouisync-native-panel"', html)
        self.assertIn("/sync/providers/ouisync/repositories?", app_js)
        self.assertIn("function renderOuisyncInventory(payload)", app_js)
        self.assertIn('id="ouisync-debug-modal"', html)
        self.assertIn('id="ouisync-reset-seed"', html)
        self.assertIn('String(line.key || "")', app_js)
        self.assertIn('function runOuisyncDebugAction(action)', app_js)
        self.assertIn("if (state.logsLoading) return;", app_js)
        self.assertIn(
            'tabHomeBtn: document.getElementById("tab-home-btn")',
            app_js,
        )
        self.assertIn(
            'tabStatusBtn: document.getElementById("tab-status-btn")',
            app_js,
        )
        self.assertIn(
            'statusPanel: document.getElementById("status-panel")',
            app_js,
        )
        self.assertIn(
            'statusTitle: document.getElementById("status-title")',
            app_js,
        )
        self.assertIn(
            'providerIframe: document.getElementById("provider-iframe")',
            app_js,
        )
        self.assertIn("function setActiveTab(tab, persist = true)", app_js)
        self.assertIn("function setActiveProviderTab(providerTab, persist = true)", app_js)
        self.assertIn("function refreshProviderPanel(navigateIframe = false)", app_js)
        self.assertIn(
            'String(state.settings.lan_mode || "").toLowerCase() ===',
            app_js,
        )
        self.assertIn("loadLanGameInventory().catch(() => {});", app_js)
        self.assertIn("function currentLanMode()", app_js)
        self.assertIn("dataset.currentUrl", app_js)
        self.assertIn(
            "Background status polling must never navigate the iframe",
            app_js,
        )
        self.assertIn(
            "state.settings.provider_interfaces = Array.isArray(",
            app_js,
        )
        self.assertIn("function renderTopProviderBadges()", app_js)
        self.assertIn("function renderStatusPanel()", app_js)
        self.assertIn('providerPid("resilio")', app_js)
        self.assertIn('providerPid("ouisync")', app_js)
        self.assertIn('status.resilio_pid', app_js)
        self.assertIn('status.ouisync_pid', app_js)
        self.assertIn("function providerErrorLabel(errorText)", app_js)
        self.assertIn("providerErrorLabel(provider.last_error)", app_js)
        self.assertIn('"/settings/extra-sync-items/import-bootstrap"', app_js)
        self.assertIn("function onExtraSyncBootstrapImport()", app_js)
        bootstrap_import = app_js.split("async function onExtraSyncBootstrapImport()", 1)[1]
        bootstrap_import = bootstrap_import.split("async function onExtraSyncToggle", 1)[0]
        self.assertIn("if (result.ok === false)", bootstrap_import)
        self.assertLess(
            bootstrap_import.index("if (result.ok === false)"),
            bootstrap_import.index("settings.provider_imported"),
        )
        self.assertIn('else if (value.startsWith("ui.")) value = t(value, value);', app_js)
        self.assertIn('String(line.state || "")', app_js)
        self.assertIn("ui.ouisync_cache_servers_unreachable", app_js)
        self.assertIn("selectedSettings.cache_servers_enabled == null", app_js)
        self.assertIn("repository.content_verified", app_js)
        self.assertIn("ui.ouisync_content_verified_hint", app_js)
        self.assertIn('id="ouisync-peers-card"', html)
        self.assertIn('id="ouisync-peer-add-form"', html)
        self.assertIn('apiPost("/sync/providers/ouisync/peers"', app_js)
        self.assertIn("ui.ouisync_peers_session_hint", app_js)
        self.assertIn("if (peer.user_provided)", app_js)
        self.assertIn(
            "total > 0 ? Math.min(100, Math.floor(done * 100 / total)) : 0;", app_js
        )
        self.assertIn('id="extra-sync-import-file"', html)
        self.assertIn('id="extra-sync-import-btn"', html)
        self.assertIn('sync.provider_starting', app_js)
        self.assertIn('sync.provider_stopping', app_js)
        self.assertIn('sync.provider_failed', app_js)
        self.assertIn('sync.open_status_details', app_js)
        self.assertIn('status.lan_games_title', app_js)
        self.assertIn('status.lan_refresh_folders', app_js)
        self.assertIn('status.lan_game_updated', app_js)
        self.assertIn('el.statusLanGamesSection.hidden = true;', app_js)
        self.assertIn('renderLanGameSharePanel();', app_js)
        self.assertIn("function normalizeLogSource(raw)", app_js)
        self.assertIn("function buildLogEntries(payload)", app_js)
        self.assertIn("function renderLogsFromCache()", app_js)
        self.assertIn("function logEntrySortTime(entry)", app_js)
        self.assertIn("`${ts} [${label}] ${level} ${msg}`", app_js)
        self.assertIn("`${ts} [${label}] ${msg}`", app_js)
        self.assertIn("const timeline = Array.isArray(payload?.entries)", app_js)
        self.assertIn('/logs?limit=${normalizeLogLimit(state.logsLimit)}', app_js)
        self.assertNotIn('apiGet("/debug/log?limit=200")', app_js)
        self.assertIn('logsLimit: localStorage.getItem("llng.logs_limit") || "200"', app_js)
        self.assertIn('logsLengthLabel: document.getElementById("logs-length-label")', app_js)
        self.assertIn('logsLengthSelect: document.getElementById("logs-length-select")', app_js)
        self.assertIn('function normalizeLogLimit(raw)', app_js)
        self.assertIn('value === "unknown"', app_js)
        self.assertIn('logs.length_200', app_js)
        self.assertIn('logs.length_500', app_js)
        self.assertIn('logs.length_1000', app_js)
        self.assertIn('logs.length_2000', app_js)
        self.assertIn('logs.source_lanlauncherng', app_js)
        self.assertIn('logs.source_resilio', app_js)
        self.assertIn('logs.source_ouisync', app_js)
        self.assertIn('logs.source_unknown', app_js)
        self.assertIn('logs.source_filter', app_js)
        self.assertIn('logs.log_level', app_js)
        self.assertIn('logs.empty_filtered', app_js)
        self.assertIn('logs.level_updated', app_js)
        self.assertIn('settings.log_critical', app_js)
        self.assertIn('ui.tile_size', app_js)
        self.assertIn('ui.tile_size_medium', app_js)
        self.assertIn('ui.tab_status', app_js)
        self.assertIn('ui.tab_providers', app_js)
        self.assertIn('ui.provider_embed_hint', app_js)
        self.assertIn('sync.provider_running', app_js)
        self.assertIn("margin-left: auto;", css)
        self.assertIn(".top-provider-badges", css)
        self.assertIn(".provider-badge", css)
        self.assertIn(".app-tabs", css)
        self.assertIn(".app-tab.is-active", css)
        self.assertIn("#status-panel.tab-panel {", css)
        self.assertIn(".status-overview", css)
        self.assertIn(".status-provider-card", css)
        self.assertIn(".status-lan-games-folder-card", css)
        self.assertIn(".status-lan-games-folder-list", css)
        self.assertIn(".provider-frame-shell", css)
        self.assertIn(".provider-iframe", css)
        self.assertIn("#logs-panel.tab-panel {", css)
        self.assertIn(".logs-control", css)
        self.assertIn(".logs-line-source-lanlauncherng", css)
        self.assertIn(".logs-line-source-resilio", css)
        self.assertIn(".logs-line-source-ouisync", css)
        self.assertIn("main.layout {", css)
        self.assertIn("width: 98vw;", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", css)
        self.assertIn(".settings-field", css)
        self.assertIn(".settings-actions", css)
        self.assertIn(".settings-hint", css)
        self.assertIn(".settings-lan-games-head", css)
        self.assertIn(".settings-lan-games-folder-list", css)
        self.assertIn("#save-settings-btn.is-dirty", css)
        self.assertIn("@keyframes settings-save-border-pulse", css)
        self.assertIn("grid-template-columns: repeat(3, minmax(0, 1fr));", css)
        self.assertIn("grid-template-areas:", css)
        self.assertIn('"general library network"', css)
        self.assertIn('"general manual manual"', css)
        self.assertIn('"lan-games lan-games lan-games"', css)
        self.assertIn("grid-template-columns: repeat(2, minmax(0, 1fr));", css)
        self.assertIn(
            "return `${yyyy}/${mm}/${dd} ${hh}:${mi}:${ss}`;",
            app_js,
        )
        self.assertIn("height: calc(100vh - 138px);", css)
        self.assertIn("white-space: pre-wrap;", css)
        self.assertIn("flex-direction: column;", css)
        self.assertIn("flex: 0 1 var(--top-traffic-basis, 11.75rem);", css)
        self.assertIn("max-width: var(--top-traffic-max-width, 12.25rem);", css)
        self.assertIn("border-radius: 10px;", css)
        self.assertIn("left: 50%;", css)
        self.assertIn("top: calc(100% + 0.5rem);", css)
        self.assertIn("min-width: 18rem;", css)
        self.assertIn("max-width: 18rem;", css)
        self.assertIn("grid-template-columns: minmax(0, 1fr);", css)
        self.assertIn("text-align: justify;", css)
        self.assertIn("text-justify: inter-word;", css)
        self.assertIn("hyphens: auto;", css)
        self.assertIn("display: flex;", css)
        self.assertIn("flex-wrap: wrap;", css)
        self.assertIn(".filters > input[type=\"search\"]", css)
        self.assertIn(".filters > button,", css)
        self.assertIn(
            "grid-template-columns: repeat(var(--grid-cols, 4), minmax(0, 1fr));",
            css,
        )

    def test_index_includes_manifest_and_favicon_links(self) -> None:
        html = Path("src/frontend/app/index.html").read_text(encoding="utf-8")
        self.assertIn('rel="manifest" href="/app/manifest.webmanifest"', html)
        self.assertIn("/assets/icons/lanlauncherng.ico", html)
        self.assertIn("/assets/icons/lanlauncherng.png", html)
        self.assertIn('id="tab-home-btn"', html)
        self.assertIn('id="tab-status-btn"', html)
        self.assertIn('id="tab-providers-btn"', html)
        self.assertIn('id="tab-settings-btn"', html)
        self.assertIn('id="tab-logs-btn"', html)
        self.assertIn('id="top-provider-badges"', html)
        self.assertIn('id="status-panel"', html)
        self.assertIn('id="providers-panel"', html)
        self.assertIn('id="provider-iframe"', html)
        self.assertIn('id="settings-section-general"', html)
        self.assertIn('>Launcher mode</label', html)
        self.assertIn('id="settings-section-library"', html)
        self.assertIn('id="settings-section-network"', html)
        self.assertLess(
            html.index('id="extra-sync-title"'),
            html.index('id="status-lan-games-section"'),
        )
        self.assertIn('id="status-lan-games-section"', html)
        self.assertIn('class="settings-lan-games-head"', html)
        self.assertIn('id="status-lan-games-status"', html)
        self.assertIn("status-lan-games-folder-list", html)
        self.assertIn('placeholder="/media/library"', html)
        self.assertIn('id="sync-only-mode-checkbox"', html)
        self.assertIn('id="install-anyway-btn"', html)
        self.assertIn('id="detail-fully-synced-badge"', html)
        self.assertIn('id="startup-screen"', html)
        self.assertIn('id="top-traffic-toggle"', html)
        self.assertIn('id="top-traffic-chart"', html)
        self.assertIn('id="top-traffic-info"', html)
        self.assertIn('id="top-traffic-info-hint"', html)
        self.assertIn('id="logs-source-filter-select"', html)
        self.assertIn('value="unknown">Unknown</option>', html)
        self.assertIn('id="logs-level-select"', html)
        self.assertIn('class="settings-group"', html)
        self.assertIn('class="settings-field"', html)
        self.assertIn('class="settings-actions"', html)
        self.assertIn('id="extra-sync-title"', html)
        self.assertIn('id="extra-sync-add-btn"', html)
        self.assertIn('id="extra-sync-import-btn"', html)
        self.assertNotIn('id="top-sync-webui"', html)
        self.assertNotIn('id="settings-toggle-btn"', html)
        self.assertNotIn('id="logs-toggle-btn"', html)
        self.assertLess(html.index('class="detail-media"'), html.index('class="detail-text"'))
        self.assertIn('id="grid-size-select"', html)
        self.assertIn('id="label-grid-size"', html)
        self.assertNotIn('id="grid-cols-select"', html)

    def test_manifest_exists_and_references_icon_assets(self) -> None:
        manifest_path = Path("src/frontend/app/manifest.webmanifest")
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        icons = manifest.get("icons", [])
        self.assertTrue(
            any(item.get("src") == "/assets/icons/lanlauncherng.png" for item in icons)
        )
        self.assertTrue(
            any(item.get("src") == "/assets/icons/lanlauncherng.ico" for item in icons)
        )


if __name__ == "__main__":
    unittest.main()
