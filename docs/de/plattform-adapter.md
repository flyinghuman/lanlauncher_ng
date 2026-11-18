# Plattform-Adapter

Plattformabhängige Datei-, Prozess- und Desktopintegration gehört hinter den Adapter unter `src/core/platform`. Service- und Launcher-Code sollen den Adapter aufrufen, statt Betriebssystemabfragen zu verteilen oder direkt Shellbefehle auszuführen.

Die aktuellen Adapter decken Windows und Linux ab. Der Vertrag umfasst Pfadnormalisierung, Speicherpfadprüfung, Ordner öffnen, Programme starten und plattformspezifische Laufzeitunterstützung. Windows-Startskripte öffnen eine Konsole, damit interaktive Abfragen sichtbar bleiben. Unter Linux werden Ordner mit `xdg-open` geöffnet; Windows-Spiele können über die Laufzeitintegration mit Wine oder Proton gestartet werden.

Die API bietet Plattforminformationen und grundlegende Speicheraktionen:

- `GET /platform/info`
- `GET /platform/validate-storage?path=...`
- `GET /platform/open-folder?path=...`
- `GET /platform/storage-locations` für die Laufwerks-/Pfadauswahl beim Erststart

Die Speicherpfadprüfung stellt sicher, dass der Pfad vorhanden, ein Verzeichnis und beschreibbar ist. Linux-Wine-Hilfsprogramme können unter `<library>/ng_provider/tools/` bereitgestellt werden. Wenn vorhanden, werden das dortige `winetricks` und sein Cache bevorzugt; andernfalls wird `PATH` verwendet.

Neue Plattformaktionen müssen Pfadtrenner, Prozessoptionen, Rechteerhöhung und Fallbacks im Adapter kapseln. Unterstützte Betriebssysteme mit gezielten Tests abdecken und fehlende Plattformwerkzeuge über stabile lokalisierte Fehlerschlüssel melden.
