# LANLauncherNG installieren

Diese Anleitung beschreibt die Installation unter Windows und Linux. Der Launcher und Ouisync sind in den jeweiligen Paketen enthalten. Eine zusätzliche `bootstrap.json` ist optional und wird nicht mit dieser Anleitung oder als allgemeine Beispiel-Datei ausgeliefert.

## Windows

1. Lade das Windows-x64-Setup für das gewünschte Release herunter.
2. Starte `lanlauncherng-setup-<version>.exe` und folge dem Setup.
3. Lass die Dokan-Treiberoption ausgewählt, wenn du Ouisync-Spiele installieren oder aktualisieren möchtest. Temporäre Ouisync-Mounts benötigen den Treiber. Die Installation erfordert eine Administratorbestätigung.
4. Starte LANLauncherNG. Wähle beim ersten Start den Spielebibliothekspfad und schließe den Willkommensassistenten ab.
5. Wähle bei Bedarf in den Einstellungen den Launcher-Modus **Client** oder **Server**.

### Resilio Sync optional hinzufügen

LANLauncherNG unterstützt neben Ouisync weitere Provider, darunter Resilio Sync. Die Resilio-Programmdatei und Lizenz werden nicht mit dem Launcher ausgeliefert. Besorge sie selbst und beachte Resilios [Nutzungsbedingungen](https://www.resilio.com/legal/terms-of-use/) sowie die aktuellen [Lizenzhinweise](https://help.resilio.com/hc/en-us/articles/204762369-How-to-apply-license-key-and-share-license-seats).

Lege diese Dateien vor dem Setup neben die Setup-`.exe`:

- Resilio-Binärdatei für Windows, exakt `btsync.exe` genannt.
- Deine Resilio-Lizenzdatei, exakt `llng.btskey` genannt.
- Optional eine eigene `bootstrap.json` mit zusätzlichen Provider-Einträgen.

Das Setup kopiert die Programmdatei nach `vendor/bin/windows-amd64/btsync.exe` und die Lizenz nach `vendor/licenses/resilio/llng.btskey`. Eine optionale `bootstrap.json` wird getrennt von der integrierten LLNG-Konfiguration als `config/optional-bootstrap.json` installiert und ergänzt deren Einträge. Sie überschreibt die integrierte Bootstrap nicht.

### Linux

1. Lade das Linux-x64-Installationsarchiv herunter und entpacke es.
2. Öffne ein Terminal im entpackten Ordner, in dem `install.sh` liegt.
3. Führe `sudo ./install.sh` aus. Das Skript installiert standardmäßig nach `/opt/lanlauncherng`; `PREFIX` kann den Installationspfad ändern. Auf dem Zielsystem werden `python3` und die Unterstützung zum Erstellen einer Python-venv benötigt.
4. Starte den Launcher mit `lanlauncherng` oder über den erstellten Desktop-Eintrag.
5. Wähle beim ersten Start den Spielebibliothekspfad und schließe den Willkommensassistenten ab.

### Resilio Sync optional hinzufügen

Besorge die Resilio-Programmdatei und eine Lizenz, die deine Nutzung abdeckt. LANLauncherNG enthält diese Dateien nicht. Beachte Resilios [Nutzungsbedingungen](https://www.resilio.com/legal/terms-of-use/) und die aktuellen [Lizenzhinweise](https://help.resilio.com/hc/en-us/articles/204762369-How-to-apply-license-key-and-share-license-seats).

Lege die Dateien **im entpackten Installationsordner neben `install.sh`** ab:

- Resilio-Binärdatei für Linux x64, exakt `rslsync` genannt.
- Deine Resilio-Lizenzdatei, exakt `llng.btskey` genannt.
- Optional eine eigene `bootstrap.json` mit zusätzlichen Provider-Einträgen.

Führe anschließend `sudo ./install.sh` aus. Das Skript kopiert die Binärdatei nach `vendor/bin/linux-x64/rslsync`, die Lizenz nach `vendor/licenses/resilio/llng.btskey` und setzt das Ausführungsrecht für die Binärdatei. Eine optionale `bootstrap.json` wird als `config/optional-bootstrap.json` installiert und ergänzt die integrierten Einträge.

Fehlt die Resilio-Binärdatei oder die Lizenz, wird LANLauncherNG weiterhin installiert; Resilio steht dann nicht vollständig zur Verfügung. Die Dateien neben dem `.tar.gz`-Archiv abzulegen reicht nicht: Sie müssen im entpackten Ordner neben `install.sh` liegen.

## Optionale Provider-Bootstrap

Die integrierte `config/bootstrap.json` enthält die Standard-Providerkonfiguration von LANLauncherNG. Für zusätzliche Provider kannst du vor der Installation eine eigene `bootstrap.json` neben die Windows-Setup-Datei beziehungsweise neben `install.sh` legen. Der Installer übernimmt diese als `config/optional-bootstrap.json`. Die zusätzlichen Einträge werden mit der integrierten Konfiguration zusammengeführt; eine doppelte `game_id` überschreibt keinen integrierten Eintrag.

Die folgende Form ist nur ein Schema-Beispiel. Es enthält keine echten Schlüssel, Freigaben oder verwendbaren Providerdaten und wird nicht als Datei mit dem Projekt ausgeliefert:

```json
{
  "items": [
    {
      "game_id": "<eindeutige-provider-id>",
      "game_key": "<dein-provider-schluessel-oder-link>",
      "title_en": "<provider-name-english>",
      "title_de": "<provider-name-deutsch>",
      "is_game_provider": true,
      "game_provider_type": "resilio",
      "sync_enabled": true,
      "has_game_db": false
    }
  ]
}
```

`game_id`, `game_key` und `title_en` sind erforderlich; `title_de` kann leer bleiben und wird dann aus `title_en` übernommen. `game_provider_type` wählt `resilio` oder `ouisync`. Ergänze nur Einträge, deren Schlüssel und Inhalte du kontrollierst. Veröffentliche keine privaten Schlüssel oder eingeschränkten Freigabelinks.

## Nach der Installation

- Öffne den Statusbereich und prüfe, ob der gewünschte Provider läuft.
- Für eine private LAN-Freigabe stelle den Server auf **Server** und wähle die freizugebenden Spieleordner aus. Clients verwenden **Client** und koppeln sich über die LAN-Suche und den Freigabecode.
- Weitere Hinweise stehen im [deutschen Benutzerhandbuch](docs/de/lanlauncher-nutzen.md), im [englischen Benutzerhandbuch](docs/en/using-lanlauncher.md) und in der [Provider-Referenz](docs/de/sync-provider.md).

## Deinstallation

Unter Linux kannst du das mitgelieferte `uninstall.sh` aus dem entpackten Installationsordner verwenden. Unter Windows LANLauncherNG über **Apps und Features** deinstallieren. Der Dokan-Treiber wird separat verwaltet und kann installiert bleiben, wenn du ihn für andere Anwendungen verwendest.
