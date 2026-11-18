# Frontend reference

This page documents the browser UI for contributors. Player instructions are in [Using LANLauncherNG](using-lanlauncher.md).

## Structure and runtime

The UI is a dependency-light static application:

- `src/frontend/app/index.html` defines the app shell and dialog markup.
- `src/frontend/app/app.js` handles navigation, API calls, catalog state, and rendering.
- `src/frontend/styles/main.css` contains layout and themes.
- `src/frontend/app/locales/{en,de}/ui.json` contains translated strings.

There is no frontend build step. The backend serves the files and provides the local API. The app has Home, Status, provider, Settings, and Logs views. Provider web interfaces are embedded when possible and can be opened externally. Status refresh uses polling; it updates data without reloading an open provider view.

The standard desktop launch starts a dedicated Chromium, Edge, or Brave app-mode window. Shortcut filtering for F11 and common developer tools is best-effort because the browser may handle reserved shortcuts before the page receives them. Closing the app window requests backend shutdown.

## Data and behavior boundaries

The catalog is loaded from the backend's local catalog API. Catalog state, install state, provider status, and display preferences are separate: a failed status refresh should not discard an already displayed catalog or reset the last valid progress value. Initial catalog loading remains visible while startup requests retry.

The frontend does not edit SQLite or LAN index files directly. It submits user actions to the backend, which validates changes and returns stable message keys. Server metadata editing is performed through the LAN game API; LAN index and settings publication remain backend responsibilities.

## API areas used by the UI

- `/settings` loads and saves launcher settings, including Launcher mode and platform runtime options.
- `/catalog/games` loads catalog entries and accepts search, locale, filter, and sort values.
- `/catalog/games/{game_id}/sync-status` and game action routes provide synchronization, installation, and launch state.
- `/sync/providers` and `/sync/status` provide provider availability, state, and traffic information.
- `/lan/games` handles server folder inventory, share selection, discovery, pairing, and server metadata/settings actions.
- `/logs` provides the merged in-app log view.

The server remains loopback-only. LAN discovery and pairing use their dedicated provider flow; they do not expose the local control API to the network.

## Localization and changes

Visible UI text belongs in both locale files. Keep the English and German keys in parity and use the translation helper instead of hard-coded component text. Backend failures should be rendered from stable message keys with a translated fallback.

When changing a frontend action, update its backend contract tests and the relevant bilingual player or provider documentation. Useful checks include:

```bash
./.venv/bin/python -m unittest tests.core.test_frontend_defaults
./.venv/bin/python -m unittest tests.core.test_lan_discovery_frontend
pwsh -File tools/scripts/verify-i18n.ps1
```
