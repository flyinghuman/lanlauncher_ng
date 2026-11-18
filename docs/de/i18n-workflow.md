# i18n Ablauf (Deutsch)

## Pflichtsprachen
- Englisch (`en`)
- Deutsch (`de`)

## Ablauf pro user-sichtbarem Feature
1. Übersetzungsschlüssel in `src/frontend/app/locales/en/*.json` anlegen/aktualisieren.
2. Dieselben Schlüssel in `src/frontend/app/locales/de/*.json` spiegeln.
3. In Code nur stabile Keys verwenden, keine hartcodierten UI-Texte.
4. Script für Übersetzungsparität ausführen.
5. Dokumentation in `docs/en` und `docs/de` aktualisieren.

## Backend-Strategie für Meldungen
- Backend liefert stabile Message-Keys (Beispiel: `error.tool_missing`).
- Frontend mappt Keys auf lokalisierte Texte.

## Validierung
Ausführen:

```powershell
./tools/scripts/verify-i18n.ps1
```

Das Script bricht ab, wenn EN/DE Schlüssel nicht identisch sind.
