# MAI Assistant - Suche in Ihrer Baudatenbank

[![CI](https://github.com/mrYoriichi/Search_standarts/actions/workflows/ci.yml/badge.svg)](https://github.com/mrYoriichi/Search_standarts/actions/workflows/ci.yml)

[English](README.md) | [Čeština](README.cs.md) | **Deutsch**

> 🔧 **Für Ingenieure & Entwickler:** die technische Beschreibung - Stack,
> RAG-Pipeline, Designentscheidungen - steht in
> [ARCHITECTURE.md](ARCHITECTURE.md) (Englisch). Diese Seite beschreibt das
> Produkt für seine Nutzer.

Erstellen Sie aus Ihrer eigenen Baudokumentation eine lokale Datenbank und
durchsuchen Sie sie von einem Ort aus. Dokumente, Projekte, Zeichnungen - ob
gescannt oder nicht, spielt keine Rolle.

Sie stellen eine Frage in normaler Sprache und erhalten eine kurze Antwort mit
einem Link auf genau die Seite des jeweiligen Dokuments. Sie müssen sich nicht
mehr erinnern, in welcher Datei es stand, und keine hunderte Seiten
durchblättern. Gesucht wird nach Stichwörtern und nach Bedeutung - Sie können
also so fragen, wie Sie einen Kollegen fragen würden, ohne die Formulierung
des Dokuments zu erraten.

![Suche](docs/screenshots/search.png)

## Worin sich das von normalem ChatGPT unterscheidet

Laden Sie 100 Dokumente in ChatGPT hoch, muss es bei jeder Frage alle erneut
lesen - langsam und teuer, und eine ganze Dokumentenbibliothek passt dort
ohnehin nicht hinein.

Hier übernimmt die Suche in Ihren Dokumenten der Code, und ChatGPT formuliert
nur die Antwort aus den gefundenen Fragmenten. Das macht es schnell, günstig
und präzise in der Quellenangabe.

## Dokumentformate

Die aktuelle Version arbeitet mit PDF. Darin kann alles stecken - Text, Scans,
Schemata, Tabellen, Zeichnungen, Schriftfelder, handschriftliche Notizen - all
das wird gelesen, vom Assistenten gemerkt und bei der Suche verwendet.
Gescannte Seiten ohne echten Text werden automatisch erkannt. Für Zeichnungen
und Schemata schreibt die KI zusätzlich eine Beschreibung - was dargestellt
ist, welches Objekt, welche Planungsphase - und genau diese Beschreibung hilft
später, das richtige Blatt zu finden. Handschrift wird so weit gelesen, wie
die KI sie entziffern kann.

## Datenschutz

Der Assistent wird lokal auf Ihrem Rechner installiert, läuft dort und
arbeitet mit den Dokumenten auf Ihrem Rechner. Die Datenbank und alles, was
sich der Assistent aus Ihren Dokumenten gemerkt hat, bleibt bei Ihnen; einen
Cloud-Speicher gibt es nicht.

Die Antworten formuliert ChatGPT (die OpenAI-API). Ihre Dokumente sind in
kleine Fragmente zerlegt, und gesendet werden nur die wenigen Fragmente, die
zu Ihrer Frage gehören - direkt an OpenAI mit Ihrem eigenen Schlüssel, ohne
Server des Autors und ohne Dienste Dritter dazwischen.

Eine kostenlose Registrierung ist nötig, nur damit der Autor sieht, dass die
App tatsächlich genutzt wird. Der Autor sieht weder Ihre Dokumente noch Ihre
Fragen oder Dateinamen: die App sendet anonyme Statistik - wie oft etwas
ausgeführt wurde, wie viel Zeit und Geld es gekostet hat, welche Fehler
aufgetreten sind.

Ihr OpenAI-Schlüssel liegt auf Ihrem Rechner verschlüsselt, von Windows an
Ihr Benutzerkonto gebunden: die Datendatei der App auf einen anderen Rechner
kopiert oder unter einem anderen Konto geöffnet gibt den Schlüssel nicht
preis. Programme, die unter Ihrem eigenen Konto laufen, können ihn weiterhin
nutzen - wie bei jedem gespeicherten Passwort - halten Sie den Rechner selbst
also vertrauenswürdig. Sollte der Schlüssel dennoch abhandenkommen, löschen
Sie ihn in Ihrem OpenAI-Konto und erstellen Sie einen neuen.

## Kosten

Die App selbst ist kostenlos, der Autor verdient nichts daran. Sie zahlen nur
OpenAI, und zwar direkt: einmalig für die Verarbeitung Ihrer Dokumente und
danach Cent-Beträge für Fragen.

| Aktion | gpt-5.6-luna (Standard) | gpt-5.6-sol |
|---|---|---|
| Verarbeitung einer Seite mit Schemata oder Tabellen | ~$0.002 | ~$0.04 |
| Verarbeitung eines Zeichnungsblatts | ~$0.002 | ~$0.04 |
| Eine Frage | ~$0.002 | ~$0.03 |
| Eine Frage mit starker Suche | ~$0.003 | ~$0.07 |

Seiten mit reinem Text sind fast kostenlos. Ein Dokument mit 300 Seiten kostet
mit dem Standardmodell einmalig einige Dutzend Cent (mit gpt-5.6-sol ein paar
Dollar); ein Arbeitstag voller Fragen kostet Cents.

## So funktioniert es

**1. Sie zeigen auf einen Ordner** - oder mehrere: eigene Dokumente, ganze
Projekte oder einen Netzwerkordner der Firma. Der Ordner wird verarbeitet, und
daneben entsteht eine für den Assistenten verständliche Kopie - darin sucht
er. Ihre Dateien werden nur gelesen: nichts wird verändert und nichts wird
irgendwohin kopiert.

![Bibliothek](docs/screenshots/library.png)

Fertige Projekte haben einen eigenen Tab: ein eingebundener Ordner = ein
Projekt mit seinen Berichten, Berechnungen und Zeichnungssätzen.

![Projektarchiv](docs/screenshots/archive.png)

Ist der Ordner ein gemeinsamer, zahlt nur die erste Person die Verarbeitung -
alle anderen binden denselben Ordner ein und übernehmen das fertige Ergebnis
kostenlos.

**2. Sie wählen, wo gesucht wird** - in der ganzen Datenbank oder in
bestimmten Dokumenten. Und wie: nach Stichwörtern, nach Bedeutung oder beides.
Es gibt außerdem die starke Suche, bei der sich der Assistent die Seiten
selbst ansieht und sagen kann, was auf einem Blatt gezeichnet ist oder welches
Maß eine Tabelle angibt.

**3. Sie erhalten eine kurze Antwort** und einen Link zur Quelle - direkt auf
die Seite, aus der die Antwort stammt. Fragen können Sie in jeder Sprache; die
Antwortsprache wird unabhängig von der Sprache der Oberfläche gewählt
(Englisch, Tschechisch, Deutsch).

**Wie viel hineinpasst.** Die öffentliche Version fasst insgesamt 5000 Seiten -
Bibliothek und Projektarchiv zusammen. Alles, was sich der Assistent gemerkt
hat, liegt im Arbeitsspeicher, damit die Suche sofort antwortet, und genau das
setzt die Grenze. Dokumente darüber hinaus bleiben markiert in der Liste und
werden einfach nicht durchsucht.

## Erste Schritte

1. **Laden Sie den Installer** für Windows herunter - er braucht keine
   Administratorrechte. *(Der öffentliche Build wird vorbereitet und erscheint
   auf der Seite
   [Releases](https://github.com/mrYoriichi/Search_standarts/releases).)*
2. **Registrieren Sie sich** beim ersten Start - E-Mail und Passwort,
   kostenlos, kein Abo.
3. **Besorgen Sie einen OpenAI-Schlüssel:** Konto auf
   [platform.openai.com](https://platform.openai.com) anlegen → **Billing →
   Add credits** ($5 reichen lange) → **API keys → Create new secret key** →
   den Schlüssel in der App unter **Einstellungen** einfügen. Er wird nur auf
   Ihrem Rechner gespeichert.
4. **Binden Sie einen Ordner** mit Ihren Dokumenten ein, drücken Sie
   **Scannen** und danach **Indexieren**.

**Die App öffnet sich in einem Browserfenster - das ist nur ihre Oberfläche,
keine Website.** Das Programm ist auf Ihrem Rechner installiert und läuft
dort; der Browser dient lediglich als Fenster.

## Über den Autor

Die App wurde von einem Brückeningenieur für Planer gebaut, aus dem eigenen
Arbeitsalltag heraus. Die öffentliche Windows-Version ist kostenlos.

## Für Entwickler

Architektur, Entwurfsentscheidungen, gemessene Zahlen und Start aus dem
Quellcode: **[ARCHITECTURE.md](ARCHITECTURE.md)** (auf Englisch).
Windows-Build: [BUILD.md](BUILD.md).

## Lizenz

[PolyForm Internal Use 1.0.0](LICENSE.md) - kostenlos für den Einsatz
innerhalb Ihrer Organisation, auch in kommerziellen Unternehmen; der Verkauf
der Software oder ihr Angebot an Dritte als Produkt oder Dienstleistung bleibt
beim Autor.
