Du hilfst einem Product Owner dabei, eine Teams-Zusammenfassung für die kernpunkt Knowledge Base zu erstellen.

Falls Argumente übergeben wurden: $ARGUMENTS
Erwartetes Format (alle optional): [projektname] [kanalname] [von YYYY-MM-DD] [bis YYYY-MM-DD] [github-repo]
Beispiel: mup dev-chat 2026-04-01 2026-04-27 kernpunkt/mup-team-memory

**Schritt 1 — Fehlende Angaben erfragen**

Frage nach allem, was noch nicht bekannt ist:
- Projektname (z.B. "mup", "foo-projekt")
- Teams-Kanalname (z.B. "mup-dev", "allgemein")
- Zeitraum: von welchem bis zu welchem Datum?
- GitHub-Repo für den Commit (z.B. "kernpunkt/mup-team-memory")

Sobald alle Angaben vorliegen, mache weiter.

**Schritt 2 — Teams-Nachrichten lesen**

Nutze den Microsoft-365-MCP-Server, um die Nachrichten aus dem angegebenen Kanal im angegebenen Zeitraum zu lesen.

**Schritt 3 — Zusammenfassung erstellen**

Erstelle eine Markdown-Datei mit folgendem Frontmatter (Werte entsprechend befüllen):

```
---
typ: teams-zusammenfassung
quelle_typ: teams-zusammenfassung
verbindlichkeit: hinweis
status: nicht-abgestimmt
projekt: [projektname]
kanal: [kanalname]
zeitraum_von: [von-datum]
zeitraum_bis: [bis-datum]
erstellt_von: po-manuell
erstellt_am: [heutiges datum]
---
```

Regeln für die Zusammenfassung:
- Fasse alles zusammen, was inhaltlich relevant ist — unabhängig davon, ob es ein langer Thread oder eine einzelne wichtige Info/Entscheidung ist
- Schreibe Aussagen mit Attribution: "Jan hat vorgeschlagen, dass ..." statt "Es wurde vorgeschlagen, dass ..."
- Verlinke Threads mit dem Original-Teams-Link, wo vorhanden
- Ignoriere reine Status-Updates ("erledigt", "ok", "👍"), Terminabstimmungen ohne inhaltliche Relevanz und private 1:1-Nachrichten

**Schritt 4 — Review durch den PO**

Zeige die fertige Zusammenfassung und warte auf Feedback oder Freigabe.
Passe bei Bedarf an und zeige die neue Version.

**Schritt 5 — Commit (erst nach expliziter Freigabe)**

Nach "ok", "passt", "committen" oder ähnlicher Bestätigung:
Committe die Datei via GitHub-MCP ins Repo als:
`teams/[YYYY-MM]/[bis-datum]_[kanalname].md`
auf den `main`-Branch mit Commit-Message: `docs: Teams-Zusammenfassung [kanalname] [zeitraum_von]–[zeitraum_bis]`
