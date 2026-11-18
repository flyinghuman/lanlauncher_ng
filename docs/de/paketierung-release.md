# Paketierung und Release

Diese Referenz richtet sich an Mitwirkende, die Anwendungspakete, Installer und Updatepakete bauen. `VERSION` ist die maßgebliche Versionsquelle für Anwendung und Installer. Für die Zielplattform die passenden Skripte verwenden und das Paket vor der Verteilung prüfen.

## Skripte
- Windows-Paket:
  - `tools/scripts/package-windows.ps1`
  - `packaging/windows/package-windows.ps1`
- Windows-Updater für die gebündelte Python-Runtime:
  - `tools/scripts/update-bundled-python-runtime.ps1`
- Windows-Installer:
  - `tools/scripts/build-installer-windows.ps1`
  - `tools/scripts/build-installer-and-update-windows.ps1`
  - `packaging/windows/inno/lanlauncherng.iss`
- Cross-platformes Release-Wrapping:
  - `tools/scripts/build-cross-platform-installer-and-updater.sh`
- Update-Paket + Manifest:
  - `tools/scripts/build_update_package.py`
- Catalog-Root-Public-Key einbetten:
  - `tools/scripts/register_game_catalog_root.py`
- OpenSourceGameIndex oder Publisher-Register signieren:
  - `tools/scripts/sign_ogsi_document.py`
- Linux-Paket:
  - `packaging/linux/package-linux.sh`
- Linux-Installer-Bundle:
  - `tools/scripts/build-installer-linux.sh`
  - `packaging/linux/install.sh`
  - `packaging/linux/uninstall.sh`
- Artefakt-Checksummen:
  - `packaging/shared/generate-checksums.ps1`
- Icon-Generator:
  - `tools/scripts/generate-app-icons.py`

## Providerdateien in Installationspaketen

Beide Installer-Builds legen `README.md`, `README.txt` und die mitgelieferte `bootstrap.json` neben dem fertigen Installationsartefakt ab. Das Linux-Archiv enthält diese Dateien zusätzlich neben `install.sh`, damit die Provider-Vorlage nach dem Entpacken bearbeitet werden kann.

Die Bootstrap-Datei legt Provider-Katalogeinträge an; `game_provider_type` ordnet einen Eintrag Resilio oder Ouisync zu. Sie wählt weder den LLNG-Modus Client/Server noch koppelt sie einen LAN-Client oder aktiviert/deaktiviert Provider-Dienste. Ouisync ist im Paket enthalten und benötigt keinen zusätzlichen Download.

Die gebündelte Ouisync-CLI ist Upstream v0.10.2 (`ee4dffce2fb5458a821afef14a41d77abbc85926`) plus der LLNG-Patch `vendor/licenses/ouisync/LLNG-MODIFICATIONS.patch` (Manifest-Version `0.10.2+llng.1`). Upstream 0.10.x speichert erneut empfangene Leaf-Knoten wiederverwendeter Blöcke als fehlend, sodass Lese-Replikate nach Repository-Änderungen unter 100 % hängen bleiben; der Patch speichert sie als vorhanden, wenn der Block lokal liegt. Tag auschecken, Patch mit `git apply` einspielen und vor dem Build `cargo test --locked -p ouisync --lib` ausführen. Die Patch-Datei ist zugleich das MPL-2.0-Quellangebot für die geänderten Dateien und wird im Paket ausgeliefert. Linux mit `cargo build --release --locked -p ouisync-cli --features vfs --target x86_64-unknown-linux-gnu` bauen; beim Build werden FUSE-Header benötigt, zur Laufzeit Zugriff auf `/dev/fuse`. Ein Build auf dem aktuellen Entwicklungsrechner verwendet glibc-2.39-Symbole; bei einem anderen Build-Rechner vor dem Release mit `objdump -T` prüfen. Für Windows den MSVC-Target und `cargo-xwin` verwenden (nicht MinGW): `DOKAN_DLL_OUTPUT_PATH=<Ausgabeordner> cargo xwin build --target x86_64-pc-windows-msvc --release --locked -p ouisync-cli --features vfs`; anschließend `ouisync.exe`, die erzeugte `dokan2.dll` und `VCRUNTIME140.dll` im selben Ordner ausliefern. VCRUNTIME stammt aus der bereits gebündelten CPython-Runtime; Hash und Redistribution-Hinweis müssen im Manifest erhalten bleiben. Das Windows-Paket enthält außerdem das offizielle x64-MSI von Dokany v2.3.0.1000. Das Setup bietet den signierten Kerneltreiber standardmäßig ausgewählt an; er bleibt nach temporären Mounts installiert. Einen bereits vorhandenen Dokan-2-Treiber nicht still entfernen oder ersetzen. In Release-Builds Quell- und Cargo-Pfade umschreiben und danach den Entwicklerpfad-Leak-Check sowie die Manifestprüfungen beider Plattformen ausführen. ADR-0003 beschreibt diese Systemabhängigkeit und die erforderlichen Administratorrechte.

Resilio-Programm- und Lizenzdateien sind proprietär und werden von LLNG nicht weiterverteilt. Das Windows-Setup erkennt optionale Dateien `btsync.exe` und `llng.btskey` neben der Setup-EXE. Das Linux-Installationsskript erkennt `rslsync` und `llng.btskey` neben der entpackten `install.sh`. Beide Installer kopieren bereitgestellte Dateien in die konfigurierten Laufzeitpfade. Nur für die Plattform und Nutzung bestimmte Programmdateien und Lizenzen von Resilio verwenden. Dazu Resilios [Nutzungsbedingungen](https://www.resilio.com/legal/terms-of-use/), [Downloadseite](https://www.resilio.com/sync/download/) und [Lizenzanleitung](https://help.resilio.com/hc/en-us/articles/204762369-How-to-apply-license-key-and-share-license-seats) beachten.

## Tool-Manifest
- `tools/scripts/package-windows.ps1` aktualisiert vor dem Paketbau die SHA256-Werte in `tools/manifest.json`.
- Windows- und Linux-Paket-Builds prüfen vorhandene `library/`- und `ng_provider/`-Bäume im Repository mit `tools/scripts/lint_game_metadata.py`. Weitere bereitgestellte Spiele-Roots vor einem Inhalts-Release explizit an das Skript übergeben; unbekannte oder fehlerhafte Installer-Aktionen lassen die Prüfung fehlschlagen.
- `tools/scripts/build-installer-windows.ps1` aktualisiert Checksummen ebenfalls:
  - gegen die Repo-Tools, wenn der Paketbau enthalten ist
  - gegen `app/tools/manifest.json` im Paket-Root, wenn `-SkipPackageBuild` verwendet wird

## Voraussetzungen
- Git-Checkout ist lokal vorhanden.
- `VERSION`-Datei im Repo-Root ist vorhanden (Single Source of Truth für App- und Installer-Version).
- Windows-Entwicklungs-Virtualenv ist unter `.venv-dev-win` verfügbar (enthält `mkdocs` und weitere Windows-Tools).
- Der kompilierte lokale Doku-Ordner `site/` ist vorhanden (erzeugen mit `mkdocs build --strict`).
- Runtime-Paketierung:
  - Windows-Pakete liefern eine eingebettete CPython-Runtime unter `vendor/bin/windows-amd64/python` aus.
  - Linux-Pakete verwenden weiterhin `.venv-runtime-lin`.
  - Falls nicht vorhanden oder ungültig, erzeugen die Paket-Skripte die passende Runtime automatisch über `tools/scripts/build-runtime-venv.ps1` (Windows Embedded Runtime) bzw. `tools/scripts/build-runtime-venv.sh` (Linux-Venv).
  - Der Windows-Runtime-Builder lädt das offizielle `python-<version>-embed-amd64.zip` nach `.cache/python-runtime-win/`, entpackt es nach `vendor/bin/windows-amd64/python`, schreibt `python<xy>._pth` und kopiert die Python-Lizenz nach `vendor/licenses/python/LICENSE.txt`.
  - Der Linux-Runtime-Builder verwendet `python -m venv --copies`, um defekte Interpreter-Symlinks auf cross-gemounteten Dateisystemen zu vermeiden.
- Die Paket-Ausgabe enthält `site/`, wenn vorhanden; der Hilfe-Button öffnet `file://.../site/index.html` vom lokalen Dateisystem.
- Windows-Installer-Build benötigt Inno Setup 6 (`ISCC.exe`), z. B.:
  - `C:\Program Files (x86)\Inno Setup 6\ISCC.exe`
  - `P:\Programme\Inno Setup 6\ISCC.exe`
  - `$HOME/.wine/drive_c/Program Files (x86)/Inno Setup 6/ISCC.exe` (Linux + Wine)
- Linux-Installer-Bundle-Build benötigt:
  - `bash`
  - `tar`

## Build-Befehle (Windows)
0. Gebündelte Windows-Python-Runtime bei Bedarf aktualisieren:
   - neuester Patch-Release der aktuell gebündelten Serie:
     - `powershell -ExecutionPolicy Bypass -File tools/scripts/update-bundled-python-runtime.ps1`
   - neuester stabiler CPython-Release von python.org:
     - `powershell -ExecutionPolicy Bypass -File tools/scripts/update-bundled-python-runtime.ps1 -LatestStable`
   - exakte Version festlegen:
     - `powershell -ExecutionPolicy Bypass -File tools/scripts/update-bundled-python-runtime.ps1 -PythonVersion 3.14.1`
   - Verhalten des Skripts:
     - löst die Zielversion über den offiziellen python.org-FTP-Index auf
     - baut `vendor/bin/windows-amd64/python` neu auf
     - aktualisiert den `python-runtime`-Eintrag in `tools/manifest.json` mit neuer Version und SHA256 von `python.exe`
1. (Falls Icons fehlen) Icons erzeugen:
   - `.\.venv-dev-win\Scripts\python.exe tools/scripts/generate-app-icons.py`
2. Portables Windows-Paket erzeugen:
   - `powershell -ExecutionPolicy Bypass -File tools/scripts/package-windows.ps1 -OutputRoot "dist/windows/lanlauncher"`
3. Windows-Setup-EXE erzeugen (Inno Setup):
   - `powershell -ExecutionPolicy Bypass -File tools/scripts/build-installer-windows.ps1`
4. Ausgabe-Artefakt:
   - `dist/windows/installer/lanlauncherng-setup.exe`

## Cross-Platform-Release-Wrapper
Auf der Linux-Entwicklungsmaschine beide Windows- und Linux-Installer-/Updater-Artefakte mit den Repo-Defaults bauen:

```bash
bash tools/scripts/build-cross-platform-installer-and-updater.sh
```

Standard-Ausgabeorte:
- Windows-Paket: `dist/windows/lanlauncherng`
- Windows-Installer: `dist/windows/installer`
- Windows-Update-Paket: `dist/windows/update`
- Linux-Paket: `dist/linux/lanlauncherng`
- Linux-Installer: `dist/linux/installer`
- Linux-Update-Paket: `dist/linux/update`

Der Wrapper verwendet die bestehenden Release-Skripte erneut, benötigt also weiterhin `pwsh`/`bash`, `.venv`, OpenSSL und die gebündelten Signatur-Keys.

## Update-Paket und Manifest bauen
Update-Payload-ZIP und Manifest in einem Schritt erstellen:

```powershell
.\.venv-dev-win\Scripts\python.exe tools/scripts/build_update_package.py `
  --package-root dist/windows/lanlauncherng `
  --output-dir dist/windows/update `
  --install-mode directory_swap `
  --install-target-path "." `
  --preserve-paths "data" `
  --key-id llng-root-2026 `
  --register-public-key `
  --public-key secrets/llng-update-public.pem `
  --private-key secrets/llng-update-private.pem `
  --overwrite
```

Standardverhalten:
- `build_update_package.py` wählt den Paket-Builder plattformabhängig (`--package-platform auto`):
  - `dist/windows/...` -> `tools/scripts/package-windows.ps1`
  - `dist/linux/...` -> `packaging/linux/package-linux.sh`
- Mit `--skip-package-build` kann dieser Schritt übersprungen werden, wenn der Paket-Root bereits gebaut wurde.
- Vor dem ZIP-Schritt wird die Payload normalisiert und enthält immer:
  - beide Startskripte: `run.bat` und `run.sh`
  - beide gebündelten Binary-Ordner: `vendor/bin/windows-amd64` und `vendor/bin/linux-x64`
  - fuer Linux-Update-Payloads wird `.venv-runtime-lin` aus dem ZIP entfernt, damit nie das Venv der Build-Maschine ausgeliefert wird
  - Linux-Update-Manifeste ergänzen automatisch `.venv-runtime-lin` in `install.preserve_paths`, damit die lokal auf dem Zielsystem erzeugte Runtime Directory-Swap-Updates überlebt

Ausgabe:
- `dist/windows/update/lanlauncherng-update-<version>.zip`
- `dist/windows/update/update-manifest.json`

## Installer und Update-Paket zusammen bauen
Ein Befehl für beide Artefakte:

```powershell
powershell -ExecutionPolicy Bypass -File tools/scripts/build-installer-and-update-windows.ps1 `
  -PackageRoot "dist/windows/lanlauncherng" `
  -UpdateOutputDir "dist/windows/update" `
  -InstallTargetPath "." `
  -KeyId "llng-root-2026" `
  -PublicKeyPath "secrets/llng-update-public.pem" `
  -PrivateKeyPath "secrets/llng-update-private.pem"
```

Standardverhalten:
- das kombinierte Skript baut zuerst den Paket-Root und erstellt danach Installer und Update-Artefakte daraus.
- `-SkipPackageBuild` nur verwenden, wenn bewusst ein bestehender Paket-Root wiederverwendet werden soll.
- der Update-Paket-Schritt verwendet die gebündelte Laufzeit `vendor/bin/windows-amd64/python/python.exe` und nicht das Entwickler-Venv.

Standardmäßig registriert `build-installer-and-update-windows.ps1` den Public Key in
`src/core/service/app.py` (`UPDATE_MANIFEST_PUBLIC_KEYS`) bevor signiert/gebaut wird.
Mit `-SkipPublicKeyRegistration` kann dieses Verhalten deaktiviert werden.

## Hinweise zu Private Key und Signatur
- Manifest-Signaturen sind RSA-SHA256 und werden über `openssl` erzeugt.
- `build_update_package.py` erkennt OpenSSL automatisch über:
  - `PATH`
  - typische Windows-Installationen (z. B. `C:\Program Files\OpenSSL-Win64\bin\openssl.exe`)
- Falls die Erkennung fehlschlägt, `--openssl-bin "<voller Pfad zu openssl.exe>"` setzen.
- `signature.key_id` im Manifest muss zu einem im Launcher vertrauenswürdigen Public Key passen (`UPDATE_MANIFEST_PUBLIC_KEYS`).
- Bei Key-Rotation:
  1. neuen Public Key + `key_id` im Launcher hinterlegen
  2. diese Launcher-Version zuerst ausrollen
  3. danach Manifeste mit dem neuen Private Key signieren

Beispiel: Private-Key-Erzeugung (RSA 2048):

```powershell
New-Item -ItemType Directory -Force -Path "secrets" | Out-Null
& "C:\Program Files\OpenSSL-Win64\bin\openssl.exe" genpkey -algorithm RSA -out "secrets/llng-update-private.pem" -pkeyopt rsa_keygen_bits:2048
```

PowerShell-Hinweis:
- Wenn der Programm-Pfad in Anführungszeichen steht (z. B. unter `Program Files`), muss davor der Call-Operator `&` verwendet werden.

### Publisher-Root für den OpenSourceGameIndex

Die Vertrauensprüfung des Game-Katalogs verwendet einen separaten Offline-Root-Key und niemals den Update-Key. Den privaten Schlüssel auf einem Offline- oder anderweitig geschützten Rechner außerhalb des Repositorys und synchronisierter Ordner aufbewahren. Root-Key und Public Key mit OpenSSL erzeugen:

```bash
install -d -m 700 "$HOME/.local/share/llng-signing"
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:3072 -out "$HOME/.local/share/llng-signing/catalog-root-private.pem"
chmod 600 "$HOME/.local/share/llng-signing/catalog-root-private.pem"
openssl pkey -in "$HOME/.local/share/llng-signing/catalog-root-private.pem" -pubout -out "$HOME/.local/share/llng-signing/catalog-root-public.pem"
./.venv/bin/python tools/scripts/register_game_catalog_root.py \
  --public-key "$HOME/.local/share/llng-signing/catalog-root-public.pem" \
  --key-id llng-catalog-root-2026
```

Das Registrierungsskript liest nur den öffentlichen PEM-Key und bettet diesen Vertrauensanker in `src/core/catalog/publisher_trust.py` ein. Vor der Veröffentlichung signierter Version-2-Indizes die Quelldiff prüfen und eine Launcher-Version mit dem Root-Key bauen. Das Skript akzeptiert RSA-Schlüssel von 3072 bis 4096 Bit und den Exponenten 65537. Den privaten Schlüssel niemals ins Repository, Paket, Provider-Update-Verzeichnis oder Spiele-Repository kopieren. Publisher-Keys sind davon getrennt, einzeln in `trusted-publishers.json` aufgeführt und können über ein neueres root-signiertes Register widerrufen werden.

Das Vertrauensregister wird manuell und nachvollziehbar bearbeitet: Publisher-Public-Key mit Nutzung `game-index` hinzufügen oder den vorhandenen Schlüssel auf `revoked` setzen und die Registry-Sequenz erhöhen. Schlüssel-IDs nicht wiederverwenden. Das aktualisierte Register mit dem Offline-Root-Key und jeden Index mit dem zugehörigen Publisher-Schlüssel signieren:

```bash
./.venv/bin/python tools/scripts/sign_ogsi_document.py registry \
  --input trusted-publishers-draft.json \
  --output ng_provider/update/trusted-publishers.json \
  --key-id llng-catalog-root-2026 \
  --private-key "$HOME/.local/share/llng-signing/catalog-root-private.pem"
./.venv/bin/python tools/scripts/sign_ogsi_document.py index \
  --input index-draft.json \
  --output ng_provider/update/index.json \
  --key-id publisher-maintainer-1 \
  --private-key /path/to/offline/publisher-private.pem
```

Das Skript kanonisiert JSON, ruft OpenSSL auf und schreibt nur Signatur und signiertes Dokument in die Ausgabe. Es veröffentlicht oder synchronisiert keine Dateien. Das geprüfte Register und den Index manuell über den NG-Ouisync-Provider verteilen, damit Clients sie offline verifizieren können.

Das ausschließlich für Publisher bestimmte Hilfsskript und seine README sind unter `ng_provider/` versioniert; Publisher-Zugangsdaten, VPN-Konfiguration und Repository-Daten bleiben von Git ignoriert. Das Skript erstellt einen unsignierten Indexkandidaten aus allen direkten `repos/<spiel_id>/metadata.json`-Ordnern. Auf dem Seed-Rechner `python3 generate_index.py` ausführen. Standardmäßig schreibt es `/opt/ng_provider/index-draft.json` außerhalb des Seed-Baums, erhöht die Revision gegenüber vorhandenem Entwurf/signiertem Index, lässt leere Platzhalter bei Katalogspielen weg und prüft die deklarierte SHA-256-Prüfsumme jedes Ouisync-Archivs. Den Kandidaten prüfen, mit dem obigen Befehl auf dem Offline-Signierrechner signieren, den signierten Index zurückkopieren und danach erst die Spiele-Repositorys und zuletzt das `ng_provider`-Repository abgleichen. Der vollständige Ablauf einschließlich Token- und Info-Hash-Angaben steht in `ng_provider/README.md`. Das Skript ist Publisher-Infrastruktur und wird nicht in LLNG-Installer oder Updates aufgenommen.

Unsigntes Test-Manifest (wird bei produktiver Signaturprüfung nicht akzeptiert):

```powershell
.\.venv-dev-win\Scripts\python.exe tools/scripts/build_update_package.py `
  --package-root dist/windows/lanlauncherng `
  --output-dir dist/windows/update `
  --unsigned `
  --overwrite
```

## Build-Befehle (Linux)
0. (Falls Icons fehlen) Icons erzeugen:
   - `./.venv-dev-win/Scripts/python.exe tools/scripts/generate-app-icons.py`
1. Portables Linux-Paket erzeugen:
   - `bash packaging/linux/package-linux.sh dist/linux/lanlauncherng`
2. Linux-Installer-Bundle erzeugen (`tar.gz` mit Payload + Installskripten):
   - `bash tools/scripts/build-installer-linux.sh dist/linux/lanlauncherng dist/linux/installer`
3. Ausgabe-Artefakt:
   - `dist/linux/installer/lanlauncherng-installer.tar.gz`
4. Hinweis zum Installer-Payload:
  - das Installer-Archiv enthält keine vorgebaute `.venv-runtime-lin`; sie wird bei der Installation mit dem `python3` des Zielsystems neu erstellt.
   - eine Neuinstallation via `sudo ./install.sh` setzt Besitzer- und Schreibrechte für `$PREFIX/data` und `$PREFIX/config` auf den aufrufenden sudo-Benutzer.

## Checksum-Erzeugung
- Checksummen für Release-Dateien erzeugen:
  - `powershell -ExecutionPolicy Bypass -File packaging/shared/generate-checksums.ps1 -TargetPath dist`
- Ausgabe:
  - `dist/SHA256SUMS.txt`

## Validierung vor Release
1. Tests ausführen:
   - `.\.venv-dev-win\Scripts\python.exe -m unittest discover -s tests -p "test_*.py"`
2. i18n-Parität prüfen:
   - `powershell -ExecutionPolicy Bypass -File tools/scripts/verify-i18n.ps1`
3. Gebündelte Runtime-Tools prüfen:
   - `powershell -ExecutionPolicy Bypass -File tools/scripts/verify-bundle.ps1`
4. Doku im Strict-Mode bauen:
   - `.\.venv-dev-win\Scripts\python.exe -m mkdocs build --strict`

## Installer-Nutzung (Linux)
Nach dem Entpacken von `lanlauncherng-installer.tar.gz`:
1. Installieren:
   - `sudo ./install.sh`
2. Launcher starten:
   - `lanlauncherng`
3. Deinstallieren:
   - `sudo ./uninstall.sh`

Der Linux-Installer legt das Launcher-Icon auch hier ab:
- `/usr/share/pixmaps/lanlauncherng.png`
- `/root/Desktop/LANLauncherNG.desktop`
- `/home/<sudo-user>/Desktop/LANLauncherNG.desktop` (bei Installation via `sudo`)
- Bei der Installation wird `.venv-runtime-lin` mit dem `python3` des Zielsystems neu erstellt, damit die Runtime-Python-Version zum Linux-System passt.
- Bei der Installation werden schreibbare Runtime-Pfade (`data`) auf den aufrufenden sudo-Benutzer zurückgesetzt, um root-eigene Dateien nach Updates zu korrigieren.
- Nach einem erhöht ausgeführten Linux-Verzeichnisupdate stellt der Updater Besitzer und Schreibrechte des aufrufenden Benutzers auch für `config/` wieder her. Resilio speichert beim Start den installationsabhängigen absoluten `storage_path` und `pid_file` in `config/resilio/config.json`.
- Das ausgelieferte `core.json` setzt `log_path` auf `data/logs/log.txt`; falls dieser Pfad beim Start dennoch nicht schreibbar ist, weicht das Logging automatisch auf benutzer-schreibbare Pfade aus.

## Fehlerbehebung
- Falsche Version in App oder Installer:
  - `VERSION` im Repo-Root aktualisieren und Paket + Installer neu bauen.
- `ISCC.exe not found`:
  - Inno Setup 6 installieren und `build-installer-windows.ps1` erneut ausführen.
- `run.bat` Fehler:
  - Paket mit aktuellem `tools/scripts/package-windows.ps1` neu erzeugen.
- Fehlende gebündelte Tools beim Start:
  - `verify-bundle.ps1` ausführen und Paket neu bauen.
- Fehlende Runtime-Python-Umgebung im Paket:
   - Paket neu bauen; unter Windows wird `vendor/bin/windows-amd64/python/python.exe` gebündelt und unter Linux `.venv-runtime-lin`; die Startskripte nutzen die passende Runtime.
   - Unter Linux erzeugt der Paketbau `.venv-runtime-lin` neu, wenn `bin/python` nicht ausführbar ist.
- Windows-Paketbau meldet lokale Entwicklerpfade im Bundle:
   - mit `tools/scripts/package-windows.ps1` neu bauen; der Paket-Builder entfernt Python-Cache-Artefakte aus `app/src` und `app/tools` und bricht ab, wenn der Paketinhalt lokale Repo- oder Home-Pfade enthält.
- Linux-Launcher meldet fehlende `.venv-runtime-lin` beim Start über `/usr/local/bin/lanlauncherng`:
   - Paket/Installer mit `packaging/linux/package-linux.sh` neu bauen und neu installieren; `run.sh` löst Symlink-Pfade auf das tatsächliche Installationsverzeichnis auf.
- Linux-Installer meldet fehlendes System-Python:
  - `python3`/`python3-venv` auf dem Zielsystem installieren und `sudo ./install.sh` erneut ausführen.
- `run.sh` meldet, dass die gebündelte Python-Runtime nicht ausführbar ist:
  - das Dateisystem ist wahrscheinlich mit `noexec` gemountet; Paket auf ein ausführbares Dateisystem verschieben/installieren (z. B. `/opt`).
- Download der Windows-Embedded-Runtime schlägt fehl:
  - Zugriff auf `https://www.python.org/ftp/python/` prüfen und `tools/scripts/build-runtime-venv.ps1` erneut ausführen.
  - die heruntergeladene Embed-ZIP wird unter `.cache/python-runtime-win/` zwischengespeichert.
- Python-Updater wählt eine unerwartete Version:
  - `tools/scripts/update-bundled-python-runtime.ps1 -PythonVersion <exakte version>` verwenden, um die Zielversion festzunageln.
  - ohne Parameter folgt der Updater dem neuesten Patch-Release der aktuell gebündelten Major/Minor-Serie aus `tools/manifest.json`.
  - mit `-LatestStable` aktualisiert er auf die höchste stabile Version aus dem python.org-FTP-Index.
- MkDocs-Strict-Fehler:
  - Navigation/Links korrigieren und `mkdocs build --strict` erneut ausführen.

## Startup-Sicherheit
Beim Service-Bootstrap werden erforderliche gebündelte Tools aus `tools/manifest.json` validiert:
- Dateiexistenz
- SHA256-Prüfsumme (falls konfiguriert)
- Lizenzdatei vorhanden (falls konfiguriert)

## Release-Ablauf (Kurzfassung)
1. Pakete erstellen (`dist/windows`, `dist/linux`).
2. Installer-Artefakte erstellen:
   - Windows (`build-installer-windows.ps1`, benötigt Inno Setup 6 / `ISCC.exe`)
   - Linux (`build-installer-linux.sh`, erzeugt `tar.gz` mit `install.sh`/`uninstall.sh`)
3. `SHA256SUMS.txt` generieren.
4. Smoke-Tests auf frischen Maschinen ausführen.
5. Artefakte + Checksummen + zweisprachige Release-Notes veröffentlichen.
