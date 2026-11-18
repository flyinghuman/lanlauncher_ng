# LANPage Entwicklungssetup (Deutsch)

Diese Anleitung richtet eine Entwicklungsmaschine so ein, dass `LANPage` lokal unter `http://launcher.lan/` auf dem Standard-HTTP-Port `80` erreichbar ist.

## Voraussetzungen
- Docker Engine und Docker Compose Plugin sind installiert.
- Repository ist im Root-Verzeichnis `LANLauncherNG` ausgecheckt.
- Ordner `LANPage` ist im Repository-Root vorhanden.

## 1. Lokalen Hostnamen konfigurieren
Folgende Zeile in die Hosts-Datei eintragen:

```text
127.0.0.1 launcher.lan
```

Typische Pfade der Hosts-Datei:
- Windows: `C:\Windows\System32\drivers\etc\hosts`
- Linux: `/etc/hosts`

## 2. LANPage-Container starten
Im Repository-Root ausführen:

```bash
docker compose up -d --build
```

Damit wird der Service `lanpage` aus der `docker-compose.yml` gestartet und der Container-Port `80` auf Host-Port `80` veröffentlicht.

## 3. Website aufrufen
Im Browser öffnen:

```text
http://launcher.lan/
```

## 4. Befehle für den Entwicklungsalltag
- Im Hintergrund starten:
  - `docker compose up -d`
- Logs anzeigen:
  - `docker compose logs -f lanpage`
- Stoppen:
  - `docker compose down`

## 5. Validierung
- `docker compose ps` zeigt `lanpage` als laufend.
- `curl http://launcher.lan/` liefert HTML-Inhalt zurück.

## Hinweise
- Die Root-`.gitignore` enthält `/LANPage/`, damit das externe LANPage-Projekt nicht in LANLauncherNG versioniert wird.
- Falls Port `80` bereits belegt ist, zuerst den konfliktierenden Dienst stoppen.

## launcher.ini-Integration in LANLauncherNG
- LANLauncherNG ruft `http://launcher.lan/launcher.ini` regelmäßig ab.
- Wenn LANPage vorübergehend nicht erreichbar ist, verwendet LANLauncherNG den zuletzt gültigen launcher.ini-Stand weiter.
- Bei frischem Start ohne erreichbare LANPage und ohne Cache nutzt LANLauncherNG Standardverhalten (keine launcher.ini-Overrides).
- Einträge aus `disable_games` haben Vorrang; diese Spiel-IDs werden in Liste/Raster ausgeblendet und für Launcher-Aktionen gesperrt.
- Folgende Link-Schlüssel werden im Top-Bar-Dropdown angezeigt:
  - `lan_url`
  - `link_1` bis `link_5`
  - `discord_url`
  - `ts3_server`
- `lan_title` wird an den App-Titel in der Top-Bar angehängt.
- LANLauncherNG sendet zusätzlich nicht-blockierende Statistik-Updates an `stats_url` (oder Fallback `http://launcher.lan/stats.php`).
