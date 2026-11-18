# Abhängigkeits- und Tool-Bundling-Policy

## Ziele
- Laufzeit- und Build-Abhängigkeiten klein halten.
- Vollständig lauffähige Pakete ohne zusätzliche Tool-Installation sicherstellen.
- Drittanbieter-Nutzung nachvollziehbar machen.

## Abhängigkeitsklassen
### Klasse A - Standardmässig erlaubt
- Standardbibliothek
- Kleine, gepflegte Bibliotheken mit wenigen transitive Abhängigkeiten
- Bibliotheken mit kompatibler Lizenz

### Klasse B - Kurze Design-Notiz erforderlich
- Bibliotheken mit mittlerer transitive Last
- Bibliotheken in kritischen Laufzeitpfaden

### Klasse C - ADR erforderlich
- Schwere Frameworks oder Runtimes
- Abhängigkeiten mit deutlicher Grössen- oder Komplexitätssteigerung
- Abhängigkeiten, die eine separate Installation auf Nutzergeräten verlangen

## Pflichtprüfungen für neu Abhängigkeiten
1. Warum Standardbibliothek oder bestehende Bibliothek nicht ausreicht.
2. Lizenzkompatibilität.
3. Sicherheitslage und Wartungszustand.
4. Grösse und transitive Auswirkungen.
5. Exit-Strategie (Austausch bei Wartungsende).

## Regeln für gebündelte Laufzeit-Tools
- Jedes ausgelieferte Tool muss in `tools/manifest.json` stehen.
- Jeder Eintrag enthält:
  - `name`
  - `platform`
  - `path`
  - `version`
  - `sha256`
  - `license_file`
  - `required`
- Binärdateien liegen unter `vendor/bin/<platform>/`.
- Lizenztexte liegen unter `vendor/licenses/`.

## Integritätsregeln
- Beim Start werden Checksummen aller erforderlichen Tools geprüft.
- Fehlende/falsche erforderliche Tools führen zu Abbruch mit lokalisierter DE/EN Meldung.
- Optionale Tools dürfen Funktionen reduzieren, müssen aber klar warnen.
