# Entwicklungsablauf (Deutsch)

## Feature-Checkliste
1. Verhalten implementieren.
2. DE + EN Übersetzungen ergänzen.
3. Inline-Kommentare für komplexe Logik hinzufügen.
4. DE + EN Dokumentation aktualisieren.
5. TODO-Tickets aktualisieren.
6. Abhängigkeitsauswirkung prüfen.

## Qualitätsregeln für Branches
- Keine UI-Texte ohne Übersetzungsschlüssel.
- Keine Konfigurationsänderung ohne Doku-Update.
- Keine Änderung an gebündelten Tools ohne Nachverfolgbarkeit.

## Git-Hooks
Den Entwicklungs-Linter installieren und die Repository-Hooks einmal pro Klon aktivieren:

```bash
./.venv/bin/python -m pip install -r requirements-dev.txt
git config core.hooksPath .githooks
```

`pre-commit` und `pre-push` führen Ruff sowie die vollständige Unittest-Suite über die Projekt-Python-Umgebung `.venv` (Linux) oder `.venv-dev-win` (Windows) aus. Unter Windows Ruff mit `\.venv-dev-win\Scripts\python.exe -m pip install -r requirements-dev.txt` installieren. Bei fehlgeschlagenen Prüfungen wird der Commit oder Push abgebrochen.

## Tests ausführen
Tests immer im Projekt-Root (`LANLauncherNG`) mit der lokalen virtuellen Umgebung ausführen.

### Windows
```powershell
.\.venv-dev-win\Scripts\python.exe -m unittest discover -s tests
```

### Linux
```bash
./.venv/bin/python -m unittest discover -s tests
```

### Optional: einzelnes Testmodul ausführen
```powershell
.\.venv-dev-win\Scripts\python.exe -m unittest tests.core.test_api
```

### Erfolgskriterien
- Kommando endet mit Exit-Code `0`
- Zusammenfassung endet mit `OK`
