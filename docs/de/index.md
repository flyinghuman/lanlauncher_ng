# LANLauncherNG

LANLauncherNG bündelt Spielekatalog, synchronisierte Spieldateien und Startfunktionen für Windows und Linux. Der Launcher kann vorhandene Provider-Kataloge, den geteilten Katalog eines LAN-Servers und selbst angelegte Einträge für bereits vorhandene Spiele anzeigen.

## Einstieg

- [LANLauncherNG benutzen](lanlauncher-nutzen.md) erklärt die Ersteinrichtung, das Finden und Starten von Spielen sowie die Verbindung mit einem LAN-Server.
- Die [Referenz zum Spieleablauf](game-workflow.md) beschreibt unterstützte Spieleordner und Startverhalten.
- Die [Referenz zu Sync-Providern](sync-provider.md) erklärt Rollen und LAN-Freigaben für Administratoren.

## Entwicklerreferenz

Die übrigen Seiten beschreiben Architektur, APIs, Paketierung, Metadatenformate und Entwicklungsabläufe. Sie richten sich an Mitwirkende und Administratoren, die Implementierungsdetails benötigen. Die Navigation unter **Entwicklerreferenz** führt zu diesen Seiten.

## Was LANLauncherNG macht

Der Launcher zeigt Spiele aus eingerichteten Katalogen an, verwaltet synchronisierte Dateien und startet Spiele mit der verfügbaren Laufzeitumgebung. Er stellt keine Spielelizenzen bereit und hostet keine offiziellen Spieledownloads. Ein Spiel muss über einen eingerichteten Sync-Provider verfügbar oder bereits lokal vorhanden sein.

Synchronisierte Spieldateien liegen im ausgewählten Bibliotheksordner. Wähle vor dem Download ein Laufwerk mit ausreichend freiem Speicherplatz.
