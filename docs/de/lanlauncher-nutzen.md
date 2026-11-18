# LANLauncherNG benutzen

Diese Anleitung erklärt den normalen Ablauf für Spieler und die schnelle Einrichtung einer geteilten Spielebibliothek für eine LAN-Party. Die Sprache lässt sich oben in der Anwendung zwischen Deutsch und Englisch umstellen.

## Ersteinrichtung

1. Beim ersten Start den Willkommensassistenten abschließen. Anschließend unter **Einstellungen** die Einrichtung prüfen.
2. Spielernamen und Speicherort der Bibliothek festlegen. Unter Windows wird ein Laufwerksbuchstabe gewählt, unter Linux ein Pfad mit ausreichend freiem Speicherplatz.
3. **Launcher-Modus** auf **Client** lassen, außer dieser Rechner soll den LAN-Katalog bereitstellen.
4. Einstellungen speichern. Wenn ein Sync-Provider verwendet wird, das Statussymbol oben prüfen. Bei gestopptem Provider können keine Spieldateien heruntergeladen werden.

Die Bibliothek enthält synchronisierte Spieldaten. Wenn der Bibliothekspfad später geändert wird, verschiebt LANLauncherNG vorhandene Dateien nicht automatisch.

Der Erststart-Assistent fasst die Verteilungswege zusammen. Spiele aus dem OpenSourceGameIndex nutzen den mitgelieferten Ouisync-Provider und benötigen keine Kopplung mit einem Owner. Resilio/ETI bleibt ein optionaler Legacy-Provider, wenn die Veranstaltungsleitung ihn bereitstellt und konfiguriert. Benutzerdefinierte Spiele eines LLNG-Rechners werden über den separaten privaten LAN-Servermodus und dessen Freigabecode geteilt.

## Spiele finden und starten

1. Über Suche, Kategorie und Statusfilter oberhalb der Liste die Spiele eingrenzen. Ein Spiel auswählen, um Beschreibung, Version, Links und aktuellen Status zu sehen.
2. Für ein noch nicht vorhandenes Spiel **Sync starten** wählen. LAN-Spiele werden auf Anfrage heruntergeladen und nach Abschluss der Synchronisierung automatisch installiert. Bei aktivierter Option **Nur Archive synchronisieren** nach dem Download **Trotzdem installieren** wählen.
3. Nach der Installation **Spiel starten** wählen. **Server starten** verwenden, wenn das Spiel eine eigene Server-Startaktion anbietet.
4. Bei einem verfügbaren Update zuerst synchronisieren und dann die aktualisierte Version starten.

Im Detailbereich lassen sich die Bibliothek und der Ordner des ausgewählten Spiels öffnen. Die Statusanzeige unterscheidet unter anderem Download, Installation, installiert und verfügbares Update.

## Einer LAN-Spielebibliothek beitreten

Der LAN-Server muss LANLauncherNG mit verfügbarem Ouisync ausführen, die Spieldateien bereitstellen und aus dem Netzwerk der Clients erreichbar sein. LLNG übernimmt Suche und Kopplung selbst; Ouisync überträgt den Katalog und ausgewählte Spiele-Repositories.

1. Auf dem Client **Einstellungen** öffnen, bei **Launcher-Modus** **Client** wählen und speichern.
2. **LAN-Server suchen** wählen. Wird der Server nicht automatisch gefunden, seine IPv4-Adresse eingeben und erneut suchen.
3. Den gewünschten Server auswählen, den vierstelligen Freigabecode aus dessen Einstellungen eingeben und **Mit Server verbinden** wählen.
4. Warten, bis Ouisync den privaten Katalog geladen hat. Die Spiele erscheinen danach in der Liste. Ein Spiel auswählen und **Sync starten** wählen, um die Dateien aus dem jeweiligen Ouisync-Spiele-Repository zu laden.

Den Code über einen vertrauenswürdigen Weg vom Serverbetreiber erhalten. Er ist drei Tage gültig und kann für mehrere Clients verwendet werden. Im Serverbereich der Einstellungen kann er erneuert werden; dabei wird der vorherige Code sofort ungültig. Für die Anmeldung muss der Server online sein. Der synchronisierte Katalog bleibt anschließend auf dem Client verfügbar, auch wenn der Server offline ist.

Ouisync-Spiele-Repositories sind auf Clients schreibgeschützt. Metadaten, Medien und das Originalarchiv verbleiben in `.ouisync`; LLNG entpackt das Archiv nach `local/`. Lokale Einstellungen und entpackte Dateien werden nicht an den Server zurückgesendet. Ein Client mit vollständigem Repository kann ein Spiel auch nach dem Abschalten des Servers weitergeben, sofern Ouisync den anderen Peer erreicht.

## Eine LAN-Spielebibliothek bereitstellen

Als Server eignet sich ein Rechner, auf dem die angebotenen Spieldateien bereits vorhanden sind und der genügend Speicherplatz hat. Der Server kann Spiele genauso wie ein Client synchronisieren und starten.

1. In **Einstellungen** den **Launcher-Modus** auf **Server** setzen und speichern. Für die Anmeldung neuer Clients muss der Server laufen.
2. In der LAN-Spieleliste bei jedem gewünschten Spieleordner **Ordner teilen** wählen. Ordner, die bereits einem anderen Provider oder einem lokalen Spieleintrag gehören, werden nicht angeboten.
3. Fehlen einem Ordner Metadaten, **Metadaten erstellen** wählen. Mindestens eine eindeutige Spiel-ID und einen Titel eintragen; Beschreibung, Version, Startdatei, Links und Titelbild sind optional. Metadaten speichern und anschließend den Ordner teilen. LANLauncherNG legt `metadata.json` im Spieleordner an und veröffentlicht den Eintrag im LAN-Katalog.
4. Unter LAN-Server-Einstellungen auswählen, welche Katalogspiele Clients sehen, LAN-Links bearbeiten und speichern. Deaktivierte Spiele werden auf Clients ausgeblendet, sofern sie dort nicht bereits installiert sind.
5. **Freigabecode anzeigen** wählen und den angezeigten Code an die Spieler weitergeben. Mit **Freigabecode erneuern** lässt sich ein neuer Code ausstellen.

LAN-Katalog und Servereinstellungen werden mit Ouisync unter `locallansync/.ouisync` veröffentlicht. Clients erhalten daraus Spielbeschreibungen und Bilder. Spiele-Repositories werden erst auf Anfrage geladen. Für LAN-Einträge muss weder `game.db` bearbeitet noch ein Datenbankupdate verteilt werden.

Um ein Spiel nicht mehr anzubieten, beim Ordner **Lokal behalten** wählen. Der Eintrag ist dann für Clients nicht mehr verfügbar; bereits installierte Kopien und ihre Dateien bleiben erhalten. Durch erneutes Teilen wird das Spiel wieder angeboten.

## Ein bereits installiertes Spiel eintragen

Im Katalog **Lokales Spiel hinzufügen** wählen und eine eindeutige ID, einen Titel sowie bei Bedarf Startdatei und Titelbild eintragen. Ein lokaler Eintrag wird nur auf diesem Rechner gespeichert und veröffentlicht oder synchronisiert das Spiel nicht. Für die Verteilung an LAN-Clients einen vom Server geteilten Spieleordner mit Metadaten verwenden.

## Häufige Probleme

| Anzeige oder Problem | Das lässt sich prüfen |
| --- | --- |
| Es werden keine Spiele angezeigt | Bibliothekspfad, Katalogverfügbarkeit und Providerstatus prüfen. Ein neuer LAN-Client muss zuerst gekoppelt werden und `locallansync` empfangen. |
| Der LAN-Server wird nicht gefunden | Prüfen, ob beide Rechner im selben erreichbaren LAN sind. IPv4-Adresse des Servers direkt eingeben und sicherstellen, dass Ouisync auf dem Server läuft. |
| Der Code wird abgelehnt | Den richtigen Server auswählen und den aktuellen vierstelligen Code eingeben. Nach drei Tagen kann der Server einen neuen Code ausstellen. |
| Ein geteiltes Spiel fehlt | Der Serverbetreiber soll prüfen, ob der Ordner geteilt ist und gültige Metadaten hat. Die Spiel-ID darf nicht bereits im Katalog vorkommen. |
| Die Synchronisierung startet nicht | Ouisync-Status und freien Speicherplatz prüfen. Beim Server nachfragen, ob das Spiel noch geteilt wird. |
| Ein Windows-Spiel startet unter Linux nicht | In den Einstellungen eine passende Wine- oder Proton-Laufzeit einrichten und sie bei Bedarf für das Spiel auswählen. |

Weitere Informationen zu Freigaben und Providern stehen in der [Sync-Provider-Referenz](sync-provider.md). Linux-Laufzeiten beschreibt die [Referenz zum Spieleablauf](game-workflow.md).
