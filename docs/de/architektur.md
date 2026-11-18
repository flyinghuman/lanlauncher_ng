# Architektur (Deutsch)

## Komponenten auf hoher Ebene
- `src/core`: Backend-Kernservice
- `src/frontend`: moderne Benutzeroberfläche
- `tools`: Skripte und Tool-Manifeste
- `vendor`: gebündelte Binärdateien und Lizenzen
- `packaging`: plattformspezifische Paketierung

## Backend-Module
- `catalog`: Metadaten für Spiele und Tools
- `sync`: Provider-Abstraktion und Adapter
- `launcher`: Installieren/Starten/Reparieren/Entfernen
- `platform`: Windows/Linux Integrationen
- `api`: HTTP/WebSocket Endpunkte

## Abhängigkeitsstrategie
- Standardbibliothek und kleine Bibliotheken bevorzugen.
- Schwere neu Abhängigkeiten nur mit ADR.
- Der globale Ouisync-Provider verwendet die gebündelte Ouisync-CLI als isolierten Kindprozess. LLNG steuert sie über die authentifizierte Loopback-Schnittstelle mit dem reinen Python-Session-Binding aus dem Upstream. Das Binding benötigt MessagePack, das die Python-Standardbibliothek nicht mitbringt. Das kleine Python-Fallback und das Session-Paket liegen deshalb unter `vendor/python`; Clients benötigen weder Internetzugriff noch eine Paketinstallation. Während Installation und Aktualisierung mountet LLNG das gewählte Repository kurzzeitig, prüft dessen signierte Identität, entpackt das Archiv, kopiert nach dem Unmount benötigte Dateien und hebt den Mount in jedem Fall auf. Die Linux-CLI nutzt FUSE und benötigt glibc 2.39 oder neuer sowie Zugriff auf `/dev/fuse`. Unter Windows kommen die VFS-fähige MSVC-CLI, die Dokan-User-Mode-DLL, `VCRUNTIME140.dll` und ein gepinntes originales Dokany-MSI zum Einsatz. Der Installer bietet den signierten Kernel-Treiber als standardmäßig ausgewählte Installationskomponente an; dafür sind Administratorrechte erforderlich, und der Treiber bleibt auch nach temporären Mounts installiert. Private LAN-Freigaben verwenden ein eigenes Repository pro Spieleordner und erlauben auch lokale Ordner ohne globalen Datenbankeintrag. LLNG kopiert teilbare Dateien aus dem Spieleordner über einen temporären beschreibbaren Mount, lässt `local/` aus, legt `.ouisync`-Inhalte im Repository-Root ab und veröffentlicht anschließend den Read-only-Key im lokalen Katalog. Änderungen am Speicherpfad lassen vorhandene Repositorys an ihrem bisherigen Ort und gelten für neue Repositorys. Siehe [ADR-0003](../shared/adr/ADR-0003.md). Ouisync-, Dokan-, MessagePack-, Microsoft-Runtime- und CLI-Lizenzhinweise werden unter `vendor/licenses` ausgeliefert. Die CLI ist Upstream v0.10.2 mit einem LLNG-Patch am MPL-2.0-Store-Code (wiederverwendete Leaf-Knoten werden als vorhanden gespeichert); der Patch wird als `vendor/licenses/ouisync/LLNG-MODIFICATIONS.patch` ausgeliefert.
- Das Upstream-Python-Binding `ouisync.service` wurde geprüft und wird nicht verwendet: Es benötigt Python 3.11+, bindet nativen Rust-Code per `ctypes` ein und würde die Prozessisolation bei Abstürzen aufgeben, ohne LLNG eine benötigte Funktion zu bieten. Außerdem wären plattformspezifische native Artefakte und Linux-ABI-Prüfungen nötig. Die bereits gebündelte CLI mit `ouisync.session` bleibt bestehen, solange kein konkreter Funktionsbedarf diesen Tausch rechtfertigt.

## Offline-Hilfstools
- Linux-Wine-Helfer können im synchronisierten Provider-Baum unter `<library>/ng_provider/tools/` abgelegt werden.
- `winetricks` wird direkt aus `<library>/ng_provider/tools/winetricks/winetricks` verwendet, wenn vorhanden, mit gemeinsamem Cache unter `<library>/ng_provider/tools/winetricks/cache`.
- Offline-Installer für `protontricks` können daneben unter `<library>/ng_provider/tools/protontricks/` verteilt werden, damit Clients ohne Internetzugang eingerichtet werden können.
- Launcherverwaltete Spiel-Prefixe für `wine`, `proton` und `proton-ge` liegen unter `<library>/<game_id>/.compatdata/<runtime>`. Paketinstallationen und Spielstarts verwenden dieselbe Umgebung pro Spiel.
