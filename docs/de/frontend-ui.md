# Frontend-Referenz

Diese Seite dokumentiert die Browseroberfläche für Mitwirkende. Die Anleitung für Spieler steht unter [LANLauncherNG benutzen](lanlauncher-nutzen.md).

## Aufbau und Laufzeit

Die Oberfläche ist eine schlanke statische Anwendung:

- `src/frontend/app/index.html` enthält App-Rahmen und Dialog-Markup.
- `src/frontend/app/app.js` steuert Navigation, API-Aufrufe, Katalogzustand und Darstellung.
- `src/frontend/styles/main.css` enthält Layout und Themes.
- `src/frontend/app/locales/{en,de}/ui.json` enthält übersetzte Texte.

Es ist kein Frontend-Buildschritt erforderlich. Das Backend liefert die Dateien und stellt die lokale API bereit. Die Oberfläche enthält Home-, Status-, Provider-, Einstellungen- und Logs-Ansichten. Provider-Weboberflächen werden nach Möglichkeit eingebettet und können extern geöffnet werden. Statusdaten werden per Polling aktualisiert, ohne eine geöffnete Provideransicht neu zu laden.

Der normale Desktopstart öffnet ein eigenes Chromium-, Edge- oder Brave-Fenster im App-Modus. Das Abfangen von F11 und gängigen Tastenkombinationen für Entwicklertools ist best-effort, weil der Browser reservierte Tastenkombinationen vor der Webseite behandeln kann. Beim Schließen des Fensters wird das Beenden des Backends angefordert.

## Daten- und Zuständigkeitsgrenzen

Der Katalog wird über die lokale Katalog-API des Backends geladen. Katalog, Installationsstatus, Providerstatus und Anzeigeeinstellungen sind getrennt: Ein fehlgeschlagener Statusabruf soll einen bereits angezeigten Katalog nicht verwerfen oder den letzten Fortschrittswert zurücksetzen. Während der Start wiederholt wird, bleibt die Katalog-Ladeanzeige sichtbar.

Das Frontend bearbeitet SQLite- oder LAN-Indexdateien nicht direkt. Es sendet Aktionen an das Backend, das Änderungen prüft und stabile Meldungsschlüssel zurückgibt. Der Metadateneditor für Serverordner verwendet die LAN-Spiele-API; Veröffentlichung von LAN-Index und Einstellungen bleiben Aufgabe des Backends.

## Von der Oberfläche verwendete API-Bereiche

- `/settings` lädt und speichert Launcher-Einstellungen einschließlich Launcher-Modus und Plattform-Laufzeiten.
- `/catalog/games` lädt Katalogeinträge und verarbeitet Suche, Sprache, Filter und Sortierung.
- `/catalog/games/{game_id}/sync-status` und Spielaktionen liefern Synchronisierungs-, Installations- und Startstatus.
- `/sync/providers` und `/sync/status` liefern Verfügbarkeit, Status und Datenverkehr der Provider.
- `/lan/games` verwaltet Serverordner, Freigaben, Suche, Kopplung sowie Metadaten- und Servereinstellungen.
- `/logs` liefert die zusammengeführte In-App-Logansicht.

Der Server bleibt auf Loopback beschränkt. LAN-Suche und Kopplung verwenden den eigenen Provider-Ablauf und öffnen die lokale Steuerungs-API nicht im Netzwerk.

## Übersetzungen und Änderungen

Sichtbare UI-Texte gehören in beide Locale-Dateien. Englische und deutsche Schlüssel müssen übereinstimmen; Komponenten verwenden die Übersetzungsfunktion statt hartcodierter Texte. Backendfehler werden über stabile Meldungsschlüssel mit übersetztem Fallback angezeigt.

Bei einer Änderung an einer UI-Aktion auch Backend-Vertragstests und die passende deutsch- und englischsprachige Anwender- oder Providerdokumentation aktualisieren. Nützliche Prüfungen:

```bash
./.venv/bin/python -m unittest tests.core.test_frontend_defaults
./.venv/bin/python -m unittest tests.core.test_lan_discovery_frontend
pwsh -File tools/scripts/verify-i18n.ps1
```
