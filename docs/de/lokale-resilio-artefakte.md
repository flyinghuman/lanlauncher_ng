# Lokale Resilio-Artefakte

Diese Seite beschreibt den Legacy-Resilio-Pfad. Ouisync ist in LANLauncherNG gebündelt und benötigt keine separate lokale Lizenzdatei.

LANLauncherNG liefert keine Resilio-Sync-Binärdateien oder Lizenzdateien mit. Wenn du eine lokale Resilio-Version zusammen mit LANLauncherNG verteilen willst, lege die Dateien vor dem Start des Installers neben das Installationspaket oder das Installskript.

## Windows
- Benenne die heruntergeladene Resilio-Sync-Setup-Datei in `btsync.exe` um.
- Lege `btsync.exe` neben den LANLauncherNG-Installer.
- Lege `llng.btskey` neben den Installer, wenn du eine Lizenzdatei hast.
- Lege `bootstrap.json` neben den Installer, wenn benutzerdefinierte Extra-Provider automatisch mit installiert werden sollen.
  - Seed-Einträge können `game_provider_type` als `resilio` oder `ouisync` angeben.
- Während der Installation werden diese Dateien an folgende Stellen kopiert:
  - `vendor/bin/windows-amd64/btsync.exe`
  - `vendor/licenses/resilio/llng.btskey`
  - `config/bootstrap.json`

## Linux
- Lege `rslsync` neben `install.sh`.
- Lege `llng.btskey` neben `install.sh`, wenn du eine Lizenzdatei hast.
- Lege `bootstrap.json` neben `install.sh`, wenn benutzerdefinierte Extra-Provider automatisch mit installiert werden sollen.
- Während der Installation werden diese Dateien an folgende Stellen kopiert:
  - `vendor/bin/linux-x64/rslsync`
  - `vendor/licenses/resilio/llng.btskey`
  - `config/bootstrap.json`
- Fehlt `rslsync`, gibt der Installer eine Warnung aus, dass der Resilio-Modus vor der Installation ein lokales `rslsync`-Binärprogramm benötigt.

## Hinweise
- Die Dateien sind absichtlich in `.gitignore` eingetragen, damit lokale Admins ihre eigene Resilio-Installation verteilen können, ohne sie ins Repository aufzunehmen.
- Update-Manifest-Dateien behalten diese lokalen Resilio-Dateien nach Möglichkeit bei, damit ein Directory-Swap-Update ein bereits kopiertes `rslsync` oder `llng.btskey` nicht entfernt.
- Wenn andere Pfade verwendet werden sollen, `sync_binary_path` und `sync_license_key_path` in `config/core.json` oder über `LLNG_SYNC_BINARY_PATH` und `LLNG_SYNC_LICENSE_KEY_PATH` setzen.
- Ouisync ist der Standardprovider; Konfiguration siehe Sync-Provider-Referenz.
