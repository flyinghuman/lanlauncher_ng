# Kernservice

Der Python-Service koordiniert Katalog, Sync-Provider, Spieleablauf, Plattform-Adapter und lokale HTTP-API. Die Konfiguration wird aus JSON mit Umgebungsvariablen-Overrides geladen. SQLite-Migrationen laufen beim regulären Start oder lassen sich separat ausführen. Logs verwenden strukturierte Einträge und rotieren bei 10 MB.

## Entwicklungsbefehle

Service starten:

```bash
./.venv/bin/python -m src.core.main --config config/core.json
```

Datenbankpflege ohne Start von UI und API ausführen oder prüfen:

```bash
./.venv/bin/python -m src.core.main --config config/core.json --migrate-db
./.venv/bin/python -m src.core.main --config config/core.json --list-db-backups
./.venv/bin/python -m src.core.main --config config/core.json --rollback-db
```

Der Migrationsmodus erstellt ein Backup mit Zeitstempel. Beim automatischen Rollback wird das neueste Backup gewählt, dessen Schema mit dem Zielschema kompatibel ist. Mit `--rollback-source <path>` kann ein bestimmtes Backup angegeben werden. Testbefehle stehen unter [Entwicklungsablauf](entwicklung.md).

## Konfiguration und Daten

`config/core.json` ist die zentrale Konfigurationsquelle. Unterstützte Umgebungsvariablen stehen neben der jeweiligen Einstellung in der Konfiguration und der passenden Feature-Referenz. Die Laufzeitdatenbank liegt unter `data/` und wird beim Start migriert. Voreingestellte manuelle Sync-Einträge stammen aus `config/bootstrap.json`; mit `default_extra_sync_items_path` oder `LLNG_DEFAULT_EXTRA_SYNC_ITEMS_PATH` lässt sich eine andere Quelle festlegen.

Der öffentliche Spielekatalog bevorzugt `<Bibliothek>/ng_provider/update/index.json`. Der Index wird dadurch über Ouisync verteilt und funktioniert ohne Internetzugriff. Relative Bild- und Videopfade werden innerhalb dieses Provider-Ordners aufgelöst. Der Service prüft die Datei alle fünf Minuten sowie Änderungen an `game.db`-Dateien der konfigurierten Legacy-Provider. Er vergleicht die Dateimetadaten vor und nach dem Lesen, wiederholt vorübergehende Lese- oder Freigabefehler und behält den letzten gültigen Index, während Ouisync die Datei ersetzt. Der Cache wird atomar ersetzt; nicht unterstützte Schema-Versionen werden ignoriert. Signierte Version-2-Indexversionen überschreiben veraltete lokale Ouisync-Metadaten für Update-Erkennung und Spiel-Laufzeitempfehlungen. Installierte Spiele zeigen nach einer signierten Versionsänderung ein Update an; die automatische Extraktion wartet auf 100 % Ouisync-Materialisierung und prüft Archiv-Prüfsumme sowie interne Versionsdatei. Entfernte Einträge aus einem gültigen signierten Index werden zur Ausmusterung vorgemerkt; LLNG löscht den Katalogzustand nach dem Entfernen der lokalen Installation. Daher benötigt der NG-Provider keine `game.db`-Tabelle für Spielentfernungen. ETI und andere Legacy-Provider können ihre `game.db` weiterhin importieren. `game_index_url` bleibt als optionale Legacy-Quelle erhalten und wird nur verwendet, wenn der lokale Provider-Index fehlt. Cache und Legacy-Aktualisierung werden über `game_index_cache_path`, `game_index_request_timeout_seconds` und `game_index_refresh_seconds` konfiguriert.

Die Mitgliedschaft aus einem gültigen lokalen Index wird für Ouisync-Spiele in der Datenbank gespeichert. Verschwindet ein Eintrag aus dem Index, behält LLNG den Katalogdatensatz, solange die lokale Installation noch vorhanden ist. Nach der Deinstallation oder wenn der Installationszustand nicht mehr `installing` ist und der entpackte Ordner `local/` fehlt, entfernt LLNG den Katalogdatensatz samt zugehörigem Zustand. Die ausstehende Entfernung bleibt über Neustarts erhalten. Ungültige oder nur aus dem Cache gelesene Indexdaten erzeugen keine neuen ausstehenden Entfernungen; eine bereits vorgemerkte Entfernung kann nach der Deinstallation abgeschlossen werden.

Der Service kann Providerdaten aus `game.db` importieren. Eine optionale Tabelle `discarded(game_id, game_key)` fordert das Entfernen passender lokaler Katalog-/Laufzeitdatensätze und Spieldaten an. Eine Zeile wird ignoriert, wenn ihre Spiel-ID nicht im lokalen Katalog vorkommt. Diese Eingabe daher nur als administrative, potenziell destruktive Daten verwenden.

## HTTP-API und Grenzen

Die lokale Steuerungs-API bietet Status- und Versionsinformationen, Einstellungen, Katalog, Providerstatus, Logs und Aktionen für den Spieleablauf. Sie ist an Loopback gebunden und keine Fernverwaltungs-API. LAN-Suche und Kopplung verwenden einen separaten, begrenzten IPv4-UDP-Ablauf.

`GET /sync/speed` liefert Providerdurchsatz und bestmöglich ermittelte lokale Festplattenaktivität. Mit `game_id` wird der Provider des Spiels gewählt; ohne Parameter werden die Werte summiert. Unter Linux wird möglichst das Blockgerät der Bibliothek gemessen, andernfalls dienen Prozess-I/O-Zähler als Fallback.

## Update und Wiederherstellung

Beim Beenden prüft der Service standardmäßig `<effective_library_path>/ng_provider/update/update-manifest.json`. Der Pfad kann über `update_manifest_path` oder `LLNG_UPDATE_MANIFEST_PATH` geändert werden. Ein neueres Release wird nur angewendet, wenn Signatur und SHA-256-Prüfsumme der Payload gültig sind. Vertrauenswürdige öffentliche Schlüssel sind in der Anwendung hinterlegt.

Das Manifest beschreibt Payloadpfad und Prüfsumme, Installationsmodus (`noop` oder `directory_swap`), Zielpfad, zu erhaltende Pfade und optional eine Datei für die Prüfung nach der Installation. Die Updater sind plattformspezifisch:

- Windows: `scripts/wrappers/windows/llng-updater.ps1`
- Linux: `scripts/wrappers/linux/llng-updater.sh`

Der Updater entpackt die Payload in eine Staging-Umgebung, legt eine wiederherstellbare Vorversion ab, tauscht das Ziel aus und stellt erhaltene Pfade wieder her (standardmäßig `data`). Bei fehlgeschlagenem Austausch oder optionaler Gesundheitsprüfung wird zurückgerollt. Für geschützte Ziele kann Windows UAC beziehungsweise Linux `pkexec`/`sudo` anfordern. Journale und das behaltene Backup liegen unter `data/update/`.

Der API-Ablauf lautet `prepare` → `apply` → `status` abfragen → nach Bestätigung durch den Nutzer `finalize` ausführen. Erkennt der Start einen unterbrochenen Austausch, muss die Wiederherstellung ausdrücklich fortgesetzt oder abgebrochen werden. `/app/update/rollback` stellt das letzte gültige Backup wieder her, falls eines vorhanden ist. Manifest und Wrapper lassen sich über `LLNG_UPDATE_MANIFEST_PATH`, `LLNG_WINDOWS_UPDATER_SCRIPT_PATH` und `LLNG_LINUX_UPDATER_SCRIPT_PATH` überschreiben.

Feature-Flags werden aus `feature_flags_path` beziehungsweise `LLNG_FEATURE_FLAGS_PATH` geladen; `LLNG_FF_<FLAG_KEY>` überschreibt ein einzelnes Flag. `GET /app/flags` liefert aufgelöste Werte und Definitionen.
