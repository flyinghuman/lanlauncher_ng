# LANLauncherNG

LANLauncherNG ist ein quelloffener Launcher für Windows und Linux, mit dem du Spiele in einem lokalen Netzwerk organisieren, installieren und starten kannst. Er verbindet eine gemeinsame Spielebibliothek mit LAN-Freigaben und optionalen Synchronisierungsprovidern.

## Was LANLauncherNG bietet

- Spielekatalog mit installierten, lokal angelegten und bereitgestellten Spielen.
- Installation und Aktualisierung aus bereitgestellten Spielarchiven sowie Start über plattformspezifische Skripte und Metadaten.
- Einen privaten LAN-Modus mit Server- und Clientrollen, Gerätesuche, Freigabe und Peer-Verteilung.
- Ouisync für den integrierten Spieleindex und die private LAN-Verteilung.
- Weitere Provider sind ebenfalls unterstützt. Resilio Sync kann optional eingebunden werden, wenn du die passende Programmdatei und Lizenz selbst bereitstellst.
- Eine Oberfläche und Dokumentation auf Deutsch und Englisch.

LANLauncherNG liefert den Launcher und die für ihn vorgesehenen Laufzeitkomponenten. Spiele und Spieldateien werden nicht mit diesem Quellcode verteilt. Verwende nur Spiele, für die du über die nötigen Nutzungsrechte verfügst.

## Installation

Eine Anleitung für Windows und Linux, optionale Resilio-Dateien und Provider-Bootstrap-Einträge steht in [INSTALLATION.md](INSTALLATION.md). Eine zusätzliche Bootstrap-Datei für eigene Provider ist optional und wird nicht mit dieser Anleitung bereitgestellt.

## Verwendung und Dokumentation

Nach der Installation wählst du beim ersten Start den Bibliothekspfad. In den Einstellungen kannst du den Launcher als Client oder Server betreiben. Ein Server kann ausgewählte Spieleordner im LAN bereitstellen; Clients entdecken den Server und laden Spiele bei Bedarf.

- [Benutzerhandbuch auf Deutsch](docs/de/lanlauncher-nutzen.md)
- [User guide in English](docs/en/using-lanlauncher.md)
- [Sync-Provider-Referenz auf Deutsch](docs/de/sync-provider.md)
- [Sync provider reference in English](docs/en/sync-provider.md)

## Unterstützte Plattformen

- Windows x64
- Linux x64

Für temporäre Ouisync-Mounts unter Windows bietet das Setup die Installation des Dokan-Dateisystemtreibers an. Unter Linux verwendet Ouisync FUSE. Details und Voraussetzungen stehen in der [Installationsanleitung](INSTALLATION.md).

## Quellcode und Lizenz

LANLauncherNG ist unter der [GNU Affero General Public License v3 oder neuer](LICENSE) lizenziert. Beiträge und Fehlerberichte sind willkommen.
