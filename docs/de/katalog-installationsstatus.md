# Katalog und Installationsstatus

Der Katalogservice verbindet Spieldatensätze der konfigurierten Provider mit dem lokalen LLNG-Zustand in SQLite. Katalogmetadaten beschreiben ein Spiel; der Installationsstatus wird in der lokalen Bibliothek ermittelt und unterscheidet fehlend, Download, Installation und installiert. Die Providerzuordnung bestimmt, wohin Sync-Aktionen gehen.

## Katalogzuständigkeit

- Einträge offizieller Provider werden aus deren Katalogen importiert und behalten ihre Providerzuordnung.
- LAN-Einträge werden aus dem geprüften Snapshot `locallansync/.ouisync/index.json` importiert. Sie behalten ihre LAN-Zuordnung auch bei ausgeschaltetem Server.
- Rein lokale Einträge werden im Launcher angelegt und nicht synchronisiert. Beim Löschen des Katalogdatensatzes werden Spieleordner und Metadaten nicht entfernt.

Vor dem Anlegen einer Spiel-ID prüft LLNG den lokalen Katalog, den LAN-Snapshot und verfügbare offizielle Provider-Datenbanken. Die Prüfung ignoriert Groß- und Kleinschreibung. Kann eine Quelle nicht geprüft werden, wird der Eintrag abgelehnt, um eine mögliche Dublette zu verhindern.

## API

- `GET /catalog/games` liefert sichtbare Einträge und unterstützt `locale`, `q`, `genre_id`, `installed`, `sort`, `order`, `page` und `page_size`.
- `GET /catalog/games/{id}` liefert Details und Metadaten eines Eintrags.
- `GET /catalog/games/{id}/sync-status` meldet Provider- und Installationsfortschritt.
- `GET /catalog/genres?locale=en|de` liefert verfügbare Genres.
- `GET /catalog/games?visibility=hidden` liefert ausgeblendete Einträge; die Standardliste schließt sie aus.
- Das Ausblenden eines Spiels aus dem signierten Ouisync-Index bleibt dauerhaft erhalten: Regelmäßige Index-Aktualisierungen übernehmen neue Metadaten, behalten aber die Ausblendung bei.
- `POST /catalog/games/{id}/visibility` ändert die Sichtbarkeit, ohne Spieldateien anzutasten.
- `GET /catalog/rescan?force=true|false` aktualisiert den Installationsstatus.

Der Installationsstatus wird lokal gespeichert und anhand des Dateisystems aktualisiert. Ein fehlender oder ungültiger LAN-Snapshot löscht nicht den letzten gültigen Katalogstand. Beim Aufheben einer Spielfreigabe wird ein unvollständiger Download aus dem aktiven Katalogstatus entfernt; installierte Dateien bleiben erhalten.
