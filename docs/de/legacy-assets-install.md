# Legacy-Assets und Installationslogik

Diese Seite gilt nur für den Legacy-Resilio-Pfad. Ouisync verwendet das gebündelte Binärprogramm und die `ouisync_*`-Konfigurationsschlüssel.

## Integrierte Legacy-Payloads
- Legacy-Spielgrafiken wurden nach `src/frontend/assets/games` kopiert und werden paketiert.
- Legacy-Spielkatalog-DB wird in paketierten Builds nach `data/legacy/game.db` kopiert.
- Resilio Sync wird nicht mit ausgeliefert. Verwende eine lokale Installation und verknüpfe sie mit dem Launcher.
- Ouisync wird mit LANLauncherNG gebündelt und benötigt keine separate lokale Installation.
- Standard-Lokalpfade sind absichtlich in `.gitignore` eingetragen:
  - `vendor/bin/windows-amd64/btsync.exe`
  - `vendor/bin/linux-x64/rslsync`
  - `vendor/licenses/resilio/llng.btskey`
- Der Installer sucht automatisch nach diesen Dateien im selben Ordner wie das Setup bzw. das Installskript und kopiert sie an die richtigen Stellen:
  - `btsync.exe` unter Windows
  - `rslsync` unter Linux
  - `llng.btskey` auf beiden Plattformen
  - `bootstrap.json` für eigene Provider-Vorgaben
    - Seed-Einträge können `game_provider_type: resilio|ouisync` angeben
- Windows-Hinweis: Wenn Resilio ein Setup-Programm liefert, die Datei vor dem Ablegen neben dem LANLauncherNG-Installer in `btsync.exe` umbenennen.
- Wenn du andere Pfade nutzen willst, setze `sync_binary_path` und `sync_license_key_path` in `config/core.json` oder über `LLNG_SYNC_BINARY_PATH` und `LLNG_SYNC_LICENSE_KEY_PATH`.
- Die Resilio-Konfiguration bleibt lokal:
  - `config/resilio/config.json`
  - `config/resilio/config.yml`

## Installations-/Startskripte
- Installation erfolgt über Launcher-Logik:
  - `<spiel_id>.eti` bleibt für Legacy-Resilio-Inhalte erhalten; neue Pakete können `.rar` oder `.tar.gz` verwenden und das Archiv in der spiel-eigenen `metadata.json` angeben.
  - `.rar` und `.eti` werden mit UnRAR entpackt. Unter Windows wird `unrar.exe` mitgeliefert; unter Linux wird derzeit `unrar` im `PATH` erwartet. `.tar.gz` verwendet die Python-Standardbibliothek.
- Startskripte bleiben als spiel-lokale Legacy-Skripte:
  - `<library>/<game_id>/game_start.cmd`
  - `<library>/<game_id>/server_start.cmd`
- Linux-Kompatibilitäts-Wrapper:
  - `scripts/wrappers/linux/run-cmd-wrapper.sh`
  - wird nur verwendet, wenn kein `game_start.sh`/`server_start.sh` existiert.

## Erkennung bereits installierter Spiele
- Basisprüfung: Spielordner existiert im konfigurierten Library-Pfad.
- Optionale Marker-Prüfungen pro Spiel aus `config/install/checks.json`.
- Wenn Marker für ein Spiel definiert sind, muss mindestens eine Marker-Datei im Spielordner existieren.

## API-Unterstützung
- Endpunkt für Installskript-Lookup:
  - `GET /catalog/games/{id}/install-script`
