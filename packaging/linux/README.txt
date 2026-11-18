LANLAUNCHERNG FOR LINUX
-----------------------

This installer archive includes LANLauncherNG, the bundled Ouisync provider, and this guide in Markdown and plain text. The integrated provider bootstrap is included in the application payload; an optional bootstrap sidecar is included only when supplied locally.

PROVIDERS INCLUDED WITH LANLAUNCHERNG
-------------------------------------

- Ouisync is included in the Linux package. The integrated config/bootstrap.json contains the ng_provider game-provider entry routed to Ouisync.
- An optional bootstrap.json beside the installer can add legacy entries such as eti_launcher for Resilio Sync.
- LLNG can manage Ouisync and the optional Resilio provider. The integrated config/bootstrap.json seeds standard entries; an installer-side bootstrap.json, when present, adds entries to those defaults. game_provider_type routes entries to Resilio or Ouisync. Bootstrap files do not turn provider processes on or off.
- sync_enabled: true enables syncing for that entry. Set game_provider_type to ouisync or resilio to choose where that entry's folder is synchronized.

The integrated `config/bootstrap.json` is already part of the application payload. To add optional provider entries, place a `bootstrap.json` beside the setup program (or beside `install.sh` in the extracted Linux installer folder). Setup stores it separately as `config/optional-bootstrap.json`, so its entries are added to the integrated defaults rather than replacing them. Without this sidecar, only integrated entries are seeded. Seeded entries are refreshed at each LLNG start; obsolete seeded rows are removed when no longer present in either bootstrap file.

Typical fields in each object in the top-level items array are game_id, game_key, title_en, title_de, sync_enabled, is_game_provider, game_provider_type, and has_game_db. Keep the full supplied examples as a template. game_key may grant access to a sync folder; do not publish a customized file containing private keys or restricted share secrets.

bootstrap.json does not set the LLNG Launcher mode, pair this computer with a LAN server, or pair clients. Set Client or Server in LLNG Settings. Use the in-app LAN discovery and approval-code flow to connect clients to a server.

ADD RESILIO SYNC (OPTIONAL)
---------------------------

LLNG does not redistribute the Resilio executable or license file. Resilio Sync is proprietary software, and Resilio's Terms of Use (<https://www.resilio.com/legal/terms-of-use/>) prohibit redistribution of its software unless separately authorized. Obtain the software and a license that covers your use directly from Resilio's download page (<https://www.resilio.com/sync/download/>) and follow its current licensing instructions (<https://help.resilio.com/hc/en-us/articles/204762369-How-to-apply-license-key-and-share-license-seats>).

First extract lanlauncherng-installer.tar.gz. Then place these two files in the extracted folder beside install.sh:

1. The Resilio Sync Linux x64 executable, renamed exactly to rslsync.
2. Your Resilio license key file, renamed exactly to llng.btskey.

Run the installer from that folder. It copies them into vendor/bin/linux-x64/rslsync and vendor/licenses/resilio/llng.btskey, then marks the binary executable. Placing the files beside the original .tar.gz without extracting it is not sufficient. If either file is absent, installation still provides bundled Ouisync; Resilio will not be available. The license is not included in the archive.

Before installation, the extracted folder should look like this when Resilio is needed:

install.sh
uninstall.sh
bootstrap.json (optional)
rslsync
llng.btskey
README.md
README.txt
lanlauncherng/

INSTALL
-------

1. Extract lanlauncherng-installer.tar.gz.
2. Optionally provide a `bootstrap.json` sidecar to add entries, then add the Resilio files described above.
3. From the extracted folder, run sudo ./install.sh.
4. Start LANLauncherNG with lanlauncherng. Complete the first-run Welcome wizard and choose the library location.
5. Review provider status in the app. For LAN sharing, choose the Launcher mode and connect to the server in Settings.

Resilio's current downloads and license options can vary by release and usage. Verify compatibility and licensing with Resilio before distributing or using the binary. A locally supplied executable or key is not copied into the LLNG source repository.

========================================================================

LANLAUNCHERNG FÜR LINUX
-----------------------

Dieses Installationsarchiv enthält LANLauncherNG, den mitgelieferten Ouisync-Provider und diese Anleitung als Markdown- und Textdatei. Die integrierte Provider-Bootstrap-Datei liegt im Anwendungs-Payload; eine optionale Bootstrap-Sidecar wird nur bei lokaler Bereitstellung beigelegt.

MITGELIEFERTE PROVIDER
----------------------

- Ouisync ist enthalten. Die integrierte Datei config/bootstrap.json enthält den Spieleprovider-Eintrag ng_provider, der Ouisync verwendet.
- Eine optionale bootstrap.json neben dem Installer kann Legacy-Einträge wie eti_launcher für Resilio Sync ergänzen.
- LLNG kann Ouisync und den optionalen Resilio-Provider verwalten. Die integrierte config/bootstrap.json trägt Standard-Einträge ein; eine bootstrap.json neben dem Installer ergänzt diese bei Bedarf. game_provider_type ordnet Einträge Resilio oder Ouisync zu. Bootstrap-Dateien aktivieren oder deaktivieren keine Providerprozesse.
- Mit sync_enabled: true ist die Synchronisierung des Eintrags aktiviert. game_provider_type muss ouisync oder resilio sein.

Die integrierte `config/bootstrap.json` ist bereits im Anwendungs-Payload enthalten. Für zusätzliche optionale Provider-Einträge eine `bootstrap.json` neben dem Setup (oder neben `install.sh` im entpackten Linux-Installerordner) ablegen. Das Setup speichert sie separat als `config/optional-bootstrap.json`; ihre Einträge ergänzen die integrierten Einträge und ersetzen diese nicht. Ohne diese Sidecar-Datei werden nur integrierte Einträge eingetragen. Seed-Einträge werden bei jedem LLNG-Start aktualisiert und veraltete Seed-Zeilen entfernt, wenn sie in keiner der Bootstrap-Dateien mehr vorkommen.

Wichtige Felder in den Objekten des obersten items-Arrays sind game_id, game_key, title_en, title_de, sync_enabled, is_game_provider, game_provider_type und has_game_db. Die vorhandenen Beispiele vollständig als Vorlage beibehalten. game_key kann Zugriff auf einen Sync-Ordner erlauben; eine angepasste Datei mit privaten Schlüsseln oder eingeschränkten Freigabecodes nicht öffentlich verteilen.

bootstrap.json legt weder den LLNG-Launcher-Modus fest noch koppelt sie diesen Rechner mit einem LAN-Server oder genehmigt Ouisync-Geräte. Client oder Server in den LLNG-Einstellungen wählen. Clients über die LAN-Suche und den Freigabecode in der Anwendung mit einem Server verbinden.

RESILIO SYNC OPTIONAL ERGÄNZEN
------------------------------

LLNG verteilt weder die Resilio-Programmdatei noch die Lizenzdatei. Resilio Sync ist proprietär; die Nutzungsbedingungen (<https://www.resilio.com/legal/terms-of-use/>) untersagen die Weiterverteilung der Software, sofern diese nicht gesondert erlaubt wurde. Programmdatei und eine für die jeweilige Nutzung gültige Lizenz direkt bei Resilio herunterladen (<https://www.resilio.com/sync/download/>) und Resilios aktuelle Lizenzanleitung (<https://help.resilio.com/hc/en-us/articles/204762369-How-to-apply-license-key-and-share-license-seats>) beachten.

Zuerst lanlauncherng-installer.tar.gz entpacken. Dann diese beiden Dateien im entpackten Ordner neben install.sh ablegen:

1. Die Resilio-Sync-Programmdatei für Linux x64, exakt in rslsync umbenannt.
2. Die eigene Resilio-Lizenzdatei, exakt in llng.btskey umbenannt.

Den Installer aus diesem Ordner starten. Er kopiert die Dateien nach vendor/bin/linux-x64/rslsync und vendor/licenses/resilio/llng.btskey und setzt anschließend das Ausführungsrecht der Binärdatei. Dateien neben dem ursprünglichen .tar.gz abzulegen, ohne es vorher zu entpacken, reicht nicht aus. Fehlt eine der beiden Dateien, wird LANLauncherNG samt Ouisync trotzdem installiert; Resilio ist dann nicht verfügbar. Die Lizenz ist nicht im Archiv enthalten.

Der entpackte Ordner sollte bei gewünschter Resilio-Unterstützung so aussehen:

install.sh
uninstall.sh
bootstrap.json (optional)
rslsync
llng.btskey
README.md
README.txt
lanlauncherng/

INSTALLATION
------------

1. lanlauncherng-installer.tar.gz entpacken.
2. Bei Bedarf eine zusätzliche `bootstrap.json` neben dem Installer für weitere Einträge ablegen und die oben beschriebenen Resilio-Dateien ergänzen.
3. Im entpackten Ordner sudo ./install.sh ausführen.
4. LANLauncherNG mit lanlauncherng starten. Den Willkommensassistenten beim Erststart abschließen und den Bibliothekspfad auswählen.
5. Providerstatus in der Anwendung prüfen. Für LAN-Freigaben den Launcher-Modus wählen und Clients in den Einstellungen mit dem Server verbinden.

Resilios aktuelle Downloads und Lizenzoptionen unterscheiden sich je nach Version und Nutzungsart. Vor einer Verteilung oder Verwendung Kompatibilität und Lizenzierung mit Resilio prüfen. Lokal bereitgestellte Programm- oder Lizenzdateien werden nicht ins LLNG-Quellcodearchiv übernommen.
