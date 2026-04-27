Du hilfst einem Product Owner dabei, einen JIRA-Export für die kernpunkt Knowledge Base zu erstellen.

Falls Argumente übergeben wurden: $ARGUMENTS
Erwartetes Format (alle optional): [projektname] [jira-projektkey] [von YYYY-MM-DD] [bis YYYY-MM-DD] [github-repo]
Beispiel: mup MUP 2026-04-01 2026-04-27 kernpunkt/mup-jira-memory

**Schritt 1 — Fehlende Angaben erfragen**

Frage nach allem, was noch nicht bekannt ist:
- Projektname (z.B. "mup")
- JIRA-Projektkey (z.B. "MUP", "KT")
- Zeitraum: von welchem bis zu welchem Datum?
- GitHub-Repo für den Commit (z.B. "kernpunkt/mup-jira-memory")

Sobald alle Angaben vorliegen, mache weiter.

**Schritt 2 — Ticket-Liste holen und zeigen**

Nutze den Atlassian-Rovo-MCP-Server, um alle Tickets aus dem JIRA-Projekt zu holen, die im angegebenen Zeitraum auf "Done" oder "Closed" gesetzt wurden.

Zeige dem PO eine übersichtliche Liste:
- Ticket-Key und Titel
- Typ (Story / Bug / Task / Sub-task)
- Abschlussdatum

Warte dann auf Rückmeldung: Welche Tickets sollen exportiert werden? ("alle" ist möglich, einzelne Keys können ausgeschlossen werden.)

**Schritt 3 — Export-Dokument erstellen**

Für die bestätigten Tickets: Hole die vollständigen Details via JIRA-MCP.

Erstelle eine Markdown-Datei mit folgendem Frontmatter:

```
---
typ: jira-export
quelle_typ: jira-export
verbindlichkeit: niedrig
status: abgeschlossen
projekt: [projektname]
jira_project_key: [key]
zeitraum_von: [von-datum]
zeitraum_bis: [bis-datum]
erstellt_von: po-manuell
erstellt_am: [heutiges datum]
---
```

Regeln für den Export:
- Übernehme Ticket-Beschreibungen unverändert — erfinde keinen LLM-Text
- Aus Kommentaren: nur solche, die Lösungsansätze, Designentscheidungen oder technische Begründungen dokumentieren; keine reinen Status-Kommentare ("in Review", "erledigt")
- Keine laufenden oder abgebrochenen Tickets

**Schritt 4 — Review durch den PO**

Zeige das fertige Dokument und warte auf Feedback oder Freigabe.
Passe bei Bedarf an und zeige die neue Version.

**Schritt 5 — Commit (erst nach expliziter Freigabe)**

Nach "ok", "passt", "committen" oder ähnlicher Bestätigung:
Committe die Datei via GitHub-MCP ins Repo als:
`jira/[YYYY-MM]/[bis-datum]_[jira-key]-export.md`
auf den `main`-Branch mit Commit-Message: `docs: JIRA-Export [jira-key] [zeitraum_von]–[zeitraum_bis]`
