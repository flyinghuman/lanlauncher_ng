# Spiele-Metadaten

LAN-Einträge verwenden die lokal gespeicherten Index-Metadaten für Spieldetails, Links, Installationsaufgaben sowie Startdateien und Argumente, auch wenn der Server offline ist. Die LAN-Ordner-ID bleibt der Sync-Schlüssel und kann nicht durch einen Metadaten-Schlüssel ersetzt werden.

Der vom Server erzeugte Index enthält das vom Open-Source-Game-Index-Schema verlangte `generated_at_utc`. Der Zeitpunkt ändert sich nur bei einer neuen Veröffentlichung; ältere LAN-Indizes ohne dieses Feld bleiben lesbar und werden beim Veröffentlichen aktualisiert.

Das öffentliche OpenSourceGameIndex-Format Version 1 bleibt zur Katalog-Kompatibilität lesbar, kann aber keine Ouisync-Repositories autorisieren. Version 2 erhält die bestehenden Spielfelder und verlangt eine monotone `index_revision` samt Signatur. Jedes Ouisync-Spiel liefert Read-only-Token, erwarteten Repository-Info-Hash, bearbeitbare Dateien, Archiv-SHA-256 und Pfad zur Versionsdatei im Archiv in seiner `metadata.json`; der Generator übernimmt diese Werte in den signierten Index. Das Feld `version` steuert Update-Hinweise, auch wenn lokale Spieldaten noch veraltet sind. LLNG gibt Tokens nicht in normalen Katalogantworten aus und verwendet sie nur nach Prüfung von Indexsignatur und root-signiertem Vertrauensregister. `index_revision` wird für jede Veröffentlichung erhöht; Clients lehnen Rollbacks und abweichende Inhalte mit wiederverwendeter Revision ab. Das Signatur- und Registerformat ist in [ADR-0002](../shared/adr/ADR-0002.md) festgelegt.

Im synchronisierten Katalogordner liegt `trusted-publishers.json` neben `index.json`. Geprüfte Kopien werden zusammen mit dem Index-Cache im lokalen Launcher-Datenordner gespeichert. LLNG merkt sich dort die höchste akzeptierte Registry-Sequenz samt Hash sowie Index-Revision samt Hash; ältere Versionen oder abweichende Inhalte mit derselben Version werden abgelehnt. Ein widerrufener Schlüssel autorisiert keine Indizes mehr, sobald das neuere root-signierte Register eingetroffen ist. Builds ohne eingebetteten Catalog-Root-Key lehnen Version-2-Indizes ab. Der Catalog-Root ist vom Update-Schlüssel getrennt und muss in einer Launcher-Version eingebettet sein, bevor signierte Kataloge verteilt werden.

Wenn ein Benutzer ein Ouisync-Spiel auswählt, verwendet LLNG das Lesetoken ausschließlich aus dem verifizierten, signierten Index. Das Repository liegt standardmäßig unter `<library>/<spiel_id>/.ouisync/<spiel_id>` oder unter dem optionalen Ouisync-Speicherpfad. LLNG prüft den Repository-Info-Hash und die Archiv-SHA-256. Vor dem Entpacken liest es die deklarierte `version.ini` im Archiv und vergleicht sie mit der signierten Index-Version. Eine Änderung der Index-Version zeigt installierten Spielen ein Update an; die automatische Extraktion wartet, bis Ouisync die Materialisierung zu 100 % abgeschlossen hat. Danach wird das Archiv direkt nach `local/` entpackt, Metadaten, referenzierte Medien, Startdateien und signierte `editable_files` werden für die Zeit nach dem Unmount kopiert; anschließend wird der Mount aufgehoben. Das Archiv wird nicht in einen zweiten Baum kopiert. Werden Repository-Daten entfernt, wird die lokale Synchronisierung freigegeben und das entpackte Spiel bleibt installiert.

Beispiel für die LLNG-Erweiterung (ein vom Publisher ausgestelltes Nur-Lese-Token verwenden):

```json
{
  "schema_version": 2,
  "index_revision": 1,
  "games": [{
    "game_id": "example-game",
    "title": "Example Game",
    "llng": {
      "schema_version": 1,
      "distribution": {
        "provider": "ouisync",
        "read_token": "<read-only-token>",
        "info_hash": "<expected-repository-hash>",
        "editable_files": ["settings.ini"]
      }
    }
  }],
  "signature": {
    "key_id": "publisher-key-id",
    "value": "<base64-rsa-sha256-signature>"
  }
}
```

Der Signaturwert ist ein Platzhalter. Publisher signieren den kanonischen Index mit dem privaten Schlüssel, der zur aktiven Schlüssel-ID in `trusted-publishers.json` gehört.

Das maschinenlesbare, LLNG-kompatible Schema für Version 2 liegt unter `schemas/opensourcegameindex-v2.schema.json`; das separate Format des Vertrauensregisters liegt unter `schemas/opensourcegameindex-trust-v1.schema.json`. LLNG akzeptiert weiterhin Indizes der Version 1. Nicht unterstützte Hauptversionen werden abgelehnt; der letzte validierte Offline-Snapshot bleibt erhalten.

Einträge des öffentlichen Game Index unterstützen `media.image_url` und `media.video_url` sowie die bisherigen Aliase `media.image` und `media.video`.

Der LAN-Index verwendet dieselbe Struktur aus `schema_version`, `source` und `games`. Ein Snapshot der Version 1 kennzeichnet seine Quelle mit `source.id` und `source.folder_id`; jedes Spiel besitzt eine `game_id`, einen Titel und eine LLNG-Ouisync-Verteilungsberechtigung. Cover-Angaben in `media.image_url` oder `media.image` müssen relative lokale JPEG-, PNG- oder WebP-Pfade innerhalb des Katalogs sein. Der Server erzeugt `<Bibliothek>/locallansync/.ouisync/index.json` aus ausdrücklich freigegebenen Ordnern mit `metadata.json` im Root, `.ouisync/metadata.json` oder einem alten Spiele-Sidecar und kopiert lokale Cover in den Katalog. LLNG importiert einen gültigen Index beim Start und nach Änderungen; fremde Katalogeinträge und installierte Spiele bleiben beim Entfernen einer Freigabe erhalten. Unvollständige Downloads verschwinden aus der Liste; Clients pausieren entfernte Freigaben, ohne Dateien zu löschen. Installierte Spiele bleiben spielbar, können aber erst nach erneuter Freigabe wieder synchronisiert werden. Fehlt der Index oder ist er ungültig, bleibt der bestehende Katalog erhalten. Im Metadaten-Editor des Servers lässt sich eine öffentliche HTTP(S)-Bildadresse herunterladen und vor dem Speichern in ein lokales JPEG umwandeln. Bilder sind auf 8 MiB begrenzt und werden auf maximal 1600 Pixel Kantenlänge verkleinert; Weiterleitungen sind begrenzt und private Netzwerkadressen werden abgelehnt. Eine ausgewählte lokale Datei hat Vorrang vor einem heruntergeladenen Cover.

In den Server-Einstellungen lässt sich für jeden Spieleordner **Metadaten erstellen** oder **Metadaten bearbeiten** wählen. Beim Teilen eines Ordners ohne Metadaten öffnet sich zuerst das Formular. Es schreibt `metadata.json` direkt in den Spieleordner und erhält weitere vorhandene Metadatenfelder; ein `metadata/`-Unterordner wird nicht mehr angelegt. Ein lokales JPEG-, PNG- oder WebP-Cover kann ausgewählt werden; bei der Freigabe wird es in den LAN-Katalog kopiert.

Beim Hinzufügen eines lokalen Spiels oder Freigeben eines Ordners prüft LLNG die Spiel-ID unabhängig von Groß- und Kleinschreibung gegen den lokalen Katalog, den LAN-Index und verfügbare offizielle Provider-Datenbanken. Ein Duplikat wird mit einer Fehlermeldung abgelehnt; ein bestehender lokaler Eintrag kann weiterhin bearbeitet werden. Falls ein Index oder eine Provider-Datenbank nicht gelesen werden kann, schlägt die Prüfung fehl, statt einen möglicherweise kollidierenden Eintrag zu erlauben.

## Zweck der Metadaten

Portable Spielmetadaten liegen unter `<Bibliothek>/<spiel_id>/metadata.json` oder bei materialisierten Ouisync-Daten unter `<Bibliothek>/<spiel_id>/.ouisync/metadata.json`. Sie können OpenSourceGameIndex-Felder und LLNG-Verteilungsdaten enthalten. Medien- und Archivpfade beziehen sich auf den Ordner der jeweiligen Metadatendatei. Metadaten, Bilder, Videos und Archiv bleiben dort; LLNG liest Medien direkt von dort und entpackt Archive direkt von dort nach `local/`. Das frühere Layout `metadata/<spiel_id>.json` wird nur noch als lesbarer Kompatibilitäts-Fallback unterstützt.

Der Launcher liest:
- `<Bibliothek>/<spiel_id>/metadata.json` oder `<Bibliothek>/<spiel_id>/.ouisync/metadata.json` für portable Spiel- und Verteilungsmetadaten.
- `metadata/<spiel_id>.json` für ältere Katalog-Overrides.
- `metadata/<spiel_id>.jpg` / `metadata/<spiel_id>.mp4` als Medien-Fallback für ältere Einträge.

Jede JSON-Datei ist optional. Ist keine Datei vorhanden, bleiben die Katalogwerte unverändert.

## JSON-Format

Der maschinenlesbare Vertrag liegt im Quellcode unter `schemas/game-metadata-v1.schema.json` und verwendet JSON Schema Draft 2020-12. Er gilt für beide portablen Metadatenpfade und lässt unbekannte OpenSourceGameIndex-Felder für zukünftige Erweiterungen zu. LLNG prüft Pfade zusätzlich zur Laufzeit: Startdateien und lokale Medien müssen innerhalb des Metadaten-/Spieleordners bleiben; Archive müssen relative Pfade mit unterstütztem `.eti`-, `.rar`- oder `.tar.gz`-Format verwenden. Zur Laufzeit benötigt LLNG kein JSON-Schema-Paket.

Mindestfelder:

- `title` (String oder Locale-Map)
- `description` (Locale-Map mit `de`, `en` und `fr`; ältere Strings bleiben lesbar)
- katalog-aequivalente Felder (optionale Overrides):
  - `key`
  - `release_year`
  - `publisher`
  - `size_gb`
  - `max_players`
  - `master_required`
  - `version`
  - `genre` (String oder Locale-Map)
  - `genre_id`
- `lan_supported` (`true` fuer LAN-faehige Spiele, die fuer LLNG relevant sind)
- `runner` (`wine`, `proton`, `proton-ge`, `native`, `auto`, `windows` oder leer)
- `image` und `video` (optionale relative Pfade)
- `website_url`, `community_url`, `discord_url`, `download_url`, `page_url`
- `links` (Liste von Link-Objekten fuer Launcher und GitHub-Pages-Navigation)
- `game_start.file` und `game_start.args`
- `installer_tasks` oder `installer` (Liste mit Task-Objekten)
- `distribution.schema_version` (`1`) und `distribution.archive` (`file`, optionales `format`, optionale SHA-256-Prüfsumme)

Locale-Maps werden unterstützt als:
- `{"de": "...", "en": "...", "fr": "..."}`. LLNG wählt für Beschreibungen die angeforderte Sprache und fällt auf Englisch zurück; ältere Strings bleiben lesbar.

Das Publisher-Format des OpenSourceGameIndex übernimmt außerdem `size_gb`, `master_required` und den optionalen Override `game_start.file`/`game_start.args`. Diese Felder werden im signierten Index weitergegeben und von LLNG verwendet, sofern vorhanden. Die übliche Erkennung von `game_start.cmd`/`game_start.sh` bleibt der Standard.

### Beispiel

```json
{
  "title": {
    "en": "1nsane",
    "de": "1nsane"
  },
  "description": "Hier können individuelle Start- und Dependency-Notizen gespeichert werden.",
  "key": "1NSANE_GOG",
  "release_year": "2000",
  "publisher": "Codemasters",
  "size_gb": 1.45,
  "max_players": "8",
  "master_required": false,
  "version": "2000-gog",
  "genre": {
    "en": "Racing",
    "de": "Rennspiel"
  },
  "genre_id": 4,
  "lan_supported": true,
  "runner": "wine",
  "website_url": "https://example.org/game",
  "community_url": "https://example.org/forum",
  "discord_url": "https://example.org/discord",
  "download_url": "https://example.org/download",
  "image": "1nsane.jpg",
  "video": "1nsane.mp4",
  "links": [
    {
      "label": {
        "en": "Project website",
        "de": "Projekt-Website"
      },
      "url": "https://example.org/game"
    }
  ],
  "game_start": {
    "file": "game_start.cmd",
    "args": []
  },
  "distribution": {
    "schema_version": 1,
    "archive": {
      "file": "1nsane.tar.gz",
      "format": "tar.gz",
      "sha256": "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"
    }
  },
  "installer_tasks": [
    {
      "app": "directplay",
      "name": "winetricks",
      "args": "/sp- /norestart /suppressmsgboxes /nogui"
    }
  ]
}
```

## Verknüpfung mit API-Daten

- `title` und `description` ersetzen im List- und Detail-Endpunkt die Katalogtexte.
- Die Metadaten werden als Feld `metadata` im API-Response ergänzt.
- `game_start` und `installer_tasks` werden von der Runtime-Logik aktiv ausgewertet.

## Laufzeitverhalten

- `game_start.file` überschreibt beim Spielstart das Standardskript `game_start.cmd` (nicht den Server-Start). Erlaubt sind nur sichere relative Pfade innerhalb des Spielordners.
- `game_start.args` werden an die Legacy-Startargumente angehängt (`game_path`, `game_id`, `game_lang`, `player`).
- `distribution.archive.file` ist ein sicherer relativer Pfad innerhalb des Spieleordners. Unterstützt werden `.tar.gz`, `.rar` und Legacy-`.eti`-RAR-Archive. Ohne dieses Feld sucht LLNG nach `<spiel_id>.eti`, `<spiel_id>.rar` und danach `<spiel_id>.tar.gz`.
- Wenn `distribution.archive.sha256` gesetzt ist, prüft LLNG die Prüfsumme, bevor Installationsaufgaben ausgeführt oder Dateien entpackt werden. Bei Abweichungen wird die Installation abgebrochen.
- Beim Entpacken von `.tar.gz` weist LLNG absolute Pfade, Elternverzeichnis-Wechsel, symbolische Links und spezielle Dateitypen zurück, bevor Dateien nach `local/` kopiert werden. Hardlinks (GNU tar legt sie für Dateien mit gemeinsamem Inode an, zum Beispiel in Linux-AppDirs) sind nur erlaubt, wenn sie auf eine reguläre Datei verweisen, die weiter vorne im selben Archiv steht; LLNG legt sie als eigenständige Kopien an. Von den gespeicherten Rechten bleibt nur das Ausführungsrecht des Besitzers erhalten (`0755`, sonst `0644`); setuid, setgid und Schreibrechte für alle entfallen. Die Archivwurzel wird zu `local/`: Ein Archiv, dessen Einträge mit `local/` beginnen, landet in `local/local/` und muss so neu gepackt werden, dass der Inhalt von `local/` an der Archivwurzel liegt. `.rar` und `.eti` werden mit UnRAR entpackt. Unter Windows wird das gebündelte Programm verwendet; unter Linux ist derzeit `unrar` im `PATH` erforderlich.
- Für plattformspezifische Starter genügt die vorhandene Konvention `game_start.cmd` und `game_start.sh`. Eine zusätzliche Zuordnung von nativen Binärdateien ist nicht erforderlich; `game_start.file` bleibt ein optionaler Einzeldatei-Override.
- Platzhalter in `game_start.args` werden ersetzt: `$GAMEDIR`, `${GAMEDIR}`, `%GAMEDIR%` (inklusive Varianten `GAME_DIR`/`GAME_PATH`).
- Unter Linux dient `runner` als Laufzeit-Hinweis fuer CMD-Starter:
  - `wine`, `proton`, `proton-ge`, `native`, `windows`, `auto`.
  - Das per Spiel gespeicherte Runtime-Override in den Launcher-Einstellungen hat weiterhin hoehere Prioritaet.
- `installer_tasks` unterstuetzt aktuell `winetricks`/`protontricks` waehrend Install/Update unter Linux.
  - Jede Aufgabe muss `name` oder `action` auf einen dieser Werte setzen und Paketnamen unter `app` oder als Nicht-Optionswerte in `args` angeben.
  - Unbekannte Task-Namen werden sicher uebersprungen und als Konsolenhinweis ausgegeben.
  - Unter Windows werden Installer-Tasks ignoriert.

Vor der Verteilung von Spieleordnern `python tools/scripts/lint_game_metadata.py <spiele-root>` ausführen. Das Skript durchsucht `metadata.json` und `.ouisync/metadata.json` und weist fehlerhafte Task-Objekte, unbekannte Aktionsnamen, fehlende Paketnamen sowie eine nicht zum Ordner passende Spiel-ID zurück. Beide Anwendungspaket-Builds führen dieselbe Prüfung für vorhandene `library/`- und `ng_provider/`-Ordner im Repository aus. Weitere separat bereitgestellte Spiele-Roots beim Vorbereiten einer Inhaltsverteilung an den Befehl übergeben.

## Migrations-Hinweise

Fuer bestehende Lutris/Bottles-Rezepte koennen Felder so uebernommen werden:

- `name` -> `title.en` / `title.de`
- `notes` -> `description.en` / `description.de`
- `runner` -> `runner`
- `lan_supported` -> markiert, ob das Spiel einen LAN-Modus hat und fuer LLNG relevant ist
- `max_players` -> Anzahl der Spieler, die der LAN-Modus unterstuetzt
- `website_url`, `community_url`, `discord_url`, `download_url`, `page_url` -> sichtbare Links im Launcher
- `links[]` -> benutzerdefinierte Links im Detailbereich und auf den generierten Oeffentlich-Seiten
- `game.exe` oder Start-Eintrag -> `game_start.file`
- Startargumente -> `game_start.args`
- winetricks/protontricks-Schritte -> `installer_tasks[]`
- Medienpfade -> `image` / `video` (oder Fallback-Dateien `metadata/<game_id>.jpg|mp4`)

Regel fuer Medienpfade:
- Pfade immer relativ zum Metadata-Root angeben (z. B. `1nsane.jpg`, `media/1nsane.mp4`).
- Im JSON-Wert kein `metadata/`-Praefix verwenden.
