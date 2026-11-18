# Referenz zum Spieleablauf

Diese Seite beschreibt die Ordner- und Startkonventionen für Mitwirkende und Personen, die Spieleinträge vorbereiten. Die Anleitung für Spieler steht unter [LANLauncherNG benutzen](lanlauncher-nutzen.md).

## Bibliotheksstruktur

Spieleordner liegen unter dem gewählten Bibliothekspfad, normalerweise als `<library>/<game_id>`. Die Ordner-ID ist der Schlüssel des Katalogs und Providers und sollte stabil bleiben. Einen synchronisierten Ordner nicht umbenennen, ohne auch Katalogeintrag und Providerkonfiguration anzupassen.

Jedes verteilte Spiel kann `<library>/<spiel_id>/metadata.json` oder `<library>/<spiel_id>/.ouisync/metadata.json` enthalten. Der portable Feld- und Pfadvertrag steht in [`Spiele-Metadaten`](game-metadata.md#json-format) und im Quellcode-Schema `schemas/game-metadata-v1.schema.json`. `distribution.archive` kann ein `.rar`-, `.tar.gz`- oder Legacy-`.eti`-Archiv sowie dessen SHA-256-Prüfsumme festlegen. Medien- und Archivpfade beziehen sich auf den Speicherort der Metadatendatei. Für Installation und Aktualisierung mountet LLNG Ouisync-Inhalte kurzzeitig: Das Archiv wird direkt daraus gelesen und nach `local/` entpackt; Metadaten und weitere benötigte Dateien werden in den Spieleordner kopiert, ebenso die Startdateien. Ein einstellbarer Ouisync-Speicherpfad kann die Repositorys auf eine andere Disk legen. Bei einer Änderung bleiben vorhandene Repositorys an ihrem bisherigen Speicherort und werden dort weiterverwendet; neue Repositorys nutzen den ausgewählten Pfad. Werden lokale Ouisync-Daten entfernt, bleibt das entpackte Spiel installiert. LAN-Freigaben erhalten pro ausgewähltem Spieleordner ein eigenes Repository, auch wenn der Ordner nicht in der globalen LLNG-Datenbank steht. LLNG kopiert teilbare Dateien aus dem Spieleordner über einen temporären beschreibbaren Mount, lässt `local/` vollständig aus und legt Dateien aus `.ouisync` im Repository-Root ab. Bei gleichen relativen Pfaden hat `.ouisync` Vorrang. Danach veröffentlicht LLNG einen Read-only-Key im LAN-Katalog und hebt den Mount auf. Der private Katalog liegt unter `<library>/locallansync/.ouisync/index.json`. Rein lokale Katalogeinträge sind davon getrennt: Ihr Katalogdatensatz liegt in der LLNG-Datenbank, bearbeitbare Metadaten liegen im `metadata/`-Hauptordner der Bibliothek. Solche Ordner können trotzdem ausdrücklich für eine LAN-Freigabe ausgewählt werden.

## Installation und Aktualisierung

LLNG wartet auf den Abschluss der Synchronisierung und die Verfügbarkeit des konfigurierten Archivs. Danach wird es nach `local/` entpackt. Ohne expliziten Archivpfad sucht LLNG der Reihe nach nach `<spiel_id>.eti`, `<spiel_id>.rar` und `<spiel_id>.tar.gz`. Eine konfigurierte SHA-256-Prüfsumme wird vor dem Entpacken geprüft. Ouisync-Metadaten können zusätzlich den Pfad zur `version.ini` im Archiv festlegen; LLNG vergleicht diese Version vor dem Entpacken mit dem signierten Indexziel. Ändert sich die Indexversion, markiert LLNG ein installiertes Spiel als aktualisierbar und startet das automatische Update erst nach vollständiger Ouisync-Materialisierung. Bei `.tar.gz` werden Pfadwechsel, Links und spezielle Dateitypen zurückgewiesen. Falls vorhanden, werden danach `game_setup.cmd` oder `game_setup.sh` ausgeführt. Eine abgeschlossene Installation enthält üblicherweise einen Ordner `local/`; `version.ini` liefert, sofern vorhanden, die installierte Version.

LAN-Spieleordner werden bei Bedarf synchronisiert. LLNG wartet auf den Repository-Snapshot, mountet ihn nur während Installation oder Aktualisierung und hebt den Mount danach auf. Bei aktivierter Option **Nur Archive synchronisieren** startet das Entpacken erst nach der Aktion **Trotzdem installieren**.

Eine Deinstallation entfernt den installierten Ordner `local/` und Launcher-Hilfsskripte. Synchronisiertes Paket und Archiv bleiben standardmäßig erhalten. Das Aufheben einer LAN-Freigabe oder das Entfernen eines Katalogeintrags löscht keine Clientdateien. Unvollständige Downloads werden aus dem sichtbaren Katalogstatus entfernt. Installierte Kopien bleiben erhalten, können aber erst nach Rückkehr der Freigabe wieder synchronisieren.

## Startkonvention

Standardmäßig startet der Client `game_start.cmd` unter Windows beziehungsweise `game_start.sh` unter Linux. Für die Aktion **Server starten** kann `server_start.cmd` oder `server_start.sh` vorhanden sein. `game_start.file` in den Metadaten ersetzt den Client-Startpfad; `game_start.args` werden an die bisherigen Argumente angehängt:

1. Pfad des Spieleordners
2. Spiel-ID
3. ausgewählte Sprache
4. Spielername

Argumente können die Platzhalter `$GAMEDIR`, `${GAMEDIR}`, `%GAMEDIR%`, `GAME_DIR` oder `GAME_PATH` verwenden. Als Startdatei sind nur sichere relative Pfade innerhalb des Spieleordners zulässig.

Unter Linux werden native Shellskripte bevorzugt. Windows-`.cmd`-Startdateien verwenden bei entsprechender Konfiguration die Kompatibilitätslaufzeit `wine`, `proton` oder `proton-ge`; eine pro Spiel gesetzte Laufzeit kann die globale Einstellung überschreiben. Proton-Präfixe werden getrennt unter `<library>/<game_id>/.compatdata/` angelegt.

Metadatenfelder und Installationsaufgaben beschreibt [Spiele-Metadaten](game-metadata.md). Die lokale HTTP-API ist unter [Kernservice](kernservice.md) dokumentiert.
