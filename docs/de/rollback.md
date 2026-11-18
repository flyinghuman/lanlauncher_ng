# Rollback-Leitfaden (Deutsch)

## Wann ein Rollback nötig ist
- Kritischer Startup-Fehler nach Release
- Migrationsproblem mit unlesbarem Zustand
- Defektes Sync-Verhalten bei mehreren Clients

## Rollback-Schritte
1. Laufenden Launcher-Prozess stoppen.
2. Aktuelle `data/`- und `config/`-Verzeichnisse sichern.
3. Zuerst API-Rollback versuchen: `GET /app/update/rollback`.
4. Falls API-Rollback nicht verfügbar ist, Paket auf letzte stabile Release-Version zurücksetzen.
5. Vorherige `config/` wiederherstellen.
6. Falls Schema-Downgrade nicht unterstützt ist, vorherige `data/`-Sicherung wiederherstellen.
7. Launcher starten und `/health` sowie `/version` prüfen.

## Recovery bei unterbrochenem Update
- Während des Shutdown-Updates schreibt der Launcher `data/update/last-run.json` und `data/update/session-<id>.json`.
- Beim nächsten Shutdown wird ein unterbrochenes `directory_swap` als `phase=recovery_required` erkannt.
- Mit `/app/shutdown/apply?session_id=<id>&action=resume` wird der Updater fortgesetzt.
- Mit `/app/shutdown/apply?session_id=<id>&action=abort` wird die Recovery abgebrochen und ein Best-Effort-Backup wiederhergestellt.

## Verifikation
- Katalogliste funktioniert.
- Sync-Status/Speed-Endpunkte antworten.
- Frontend lädt in EN und DE.
