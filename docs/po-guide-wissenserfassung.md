# Wissenserfassung mit Claude Desktop — Anleitung für Product Owner

Mit Claude Desktop und den richtigen MCP-Servern kannst du Teams-Zusammenfassungen und JIRA-Exporte in wenigen Minuten in die Knowledge Base bringen. Claude holt die Daten, du reviewst, Claude committed.

---

## Schnellstart: Prompts verwenden

Die fertigen Prompt-Vorlagen liegen im Repo unter `skills/`. Zwei Möglichkeiten sie zu nutzen:

### Option A — Prompt kopieren (immer funktioniert)

1. Öffne [`skills/teams-zusammenfassung.md`](../skills/teams-zusammenfassung.md) oder [`skills/jira-export.md`](../skills/jira-export.md)
2. Kopiere den Inhalt
3. Füge ihn in Claude Desktop ein und passe die markierten Stellen an

### Option B — Als Claude-Projekt einrichten (empfohlen)

Lege in Claude Desktop ein Projekt an (z.B. "Wissenserfassung MUP") und hinterlege den Skill-Text als **Projekt-Systemanweisung**. Dann steht er bei jedem neuen Chat im Projekt direkt bereit — ohne Kopieren.

1. Claude Desktop → **Projekte** → Neues Projekt
2. Projektname: z.B. "Wissenserfassung [Projektname]"
3. Systemanweisung: Inhalt aus `skills/teams-zusammenfassung.md` einfügen
4. MCP-Server für das Projekt aktivieren (O365, Atlassian, GitHub)

> **Hinweis:** Das Slash-Command-System (`/befehlsname`) gibt es in Claude Desktop aktuell nicht für eigene Prompts — das ist ein Feature von Claude Code (dem CLI-Tool für Entwickler). Für POs ist die Projekt-Variante der einfachste Weg.

---

## Voraussetzungen

### MCP-Server in Claude Desktop

Du brauchst diese MCP-Server (einmalige Einrichtung durch euer IT/Dev-Team):

| MCP-Server | Wozu | Anbieter |
|---|---|---|
| **Microsoft 365 / O365** | Teams-Nachrichten lesen | `@anthropic-ai/mcp-microsoft-365` o.ä. |
| **Atlassian Rovo** | JIRA-Tickets lesen | Atlassian Rovo MCP |
| **GitHub** | Dateien committen | GitHub MCP |

> Hinweis: Welche MCP-Server genau konfiguriert sind, siehst du in Claude Desktop unter Einstellungen → MCP-Server. Wenn etwas fehlt, meldet euch beim Dev-Team.

### GitHub-Repos

Für jedes Projekt gibt es separate Memory-Repos. Beispiel:
- Teams-Zusammenfassungen: `kernpunkt/mup-team-memory`
- JIRA-Exporte: `kernpunkt/mup-jira-memory`

Wie man diese anlegt: [`setup-memory-repos.md`](setup-memory-repos.md)

---

## Teil 1: Teams-Zusammenfassung erstellen

### Wann?

Wöchentlich oder nach wichtigen Diskussionen im Projektkanal. Mindestens 3 Nachrichten pro Thread sollten vorhanden sein, damit eine Zusammenfassung sinnvoll ist.

### Prompt für Claude Desktop

Kopiere diesen Prompt und passe die fettgedruckten Stellen an:

---

```
Du bist mein Assistent für die Wissenserfassung. Ich möchte eine Teams-Zusammenfassung 
für unsere Knowledge Base erstellen.

**Aufgabe:**
Lies die Nachrichten aus dem Teams-Kanal **[Kanalname, z.B. "mup-dev"]** im Zeitraum 
**[von YYYY-MM-DD bis YYYY-MM-DD]** und erstelle eine strukturierte Zusammenfassung.

**Projektname:** [Projektname, z.B. "mup"]
**Repository für den Commit:** [z.B. "kernpunkt/mup-team-memory"]

**Regeln für die Zusammenfassung:**
- Fasse alles zusammen, was inhaltlich relevant ist — unabhängig davon, ob es ein langer Thread oder eine einzelne wichtige Info/Entscheidung ist
- Schreibe Aussagen mit Attribution: "Jan hat vorgeschlagen, dass ..." statt "Es wurde beschlossen, dass ..."
- Verlinke jeden Thread mit dem Original-Teams-Link
- Ignoriere private Nachrichten, Emoji-Reaktionen ohne Kontext und reine Terminabstimmungen
- Keine privaten 1:1-Chats

**Format der Ausgabe:** Erstelle eine Markdown-Datei mit diesem Frontmatter:
---
typ: teams-zusammenfassung
quelle_typ: teams-zusammenfassung
verbindlichkeit: hinweis
status: nicht-abgestimmt
projekt: [projektname]
kanal: [kanalname]
zeitraum_von: YYYY-MM-DD
zeitraum_bis: YYYY-MM-DD
erstellt_von: po-manuell
erstellt_am: [heutiges Datum]
---

**Vorgehensweise:**
1. Lies zuerst die Teams-Nachrichten aus dem Kanal
2. Zeige mir die Zusammenfassung zur Prüfung
3. Warte auf mein OK
4. Committe die Datei dann als `teams/YYYY-MM/YYYY-MM-DD_[kanalname].md` ins Repo 
   **[repo-name]** auf den main-Branch
```

---

### Ablauf

1. **Prompt einfügen** und absenden
2. **Claude liest die Teams-Nachrichten** (du siehst die MCP-Aufrufe)
3. **Claude zeigt dir die Zusammenfassung** — lies sie durch:
   - Sind alle wichtigen Entscheidungen drin?
   - Stimmen die Attributionen (wer hat was gesagt)?
   - Gibt es sensible Inhalte, die nicht rein sollen?
4. **Feedback geben** oder mit "Sieht gut aus, bitte committen" bestätigen
5. **Claude committed** die Datei direkt ins GitHub-Repo

---

## Teil 2: JIRA-Export erstellen

### Wann?

Am Ende eines Sprints oder Quartals — für abgeschlossene Tickets (`Done` / `Closed`). Offene Tickets werden nicht exportiert.

### Prompt für Claude Desktop

---

```
Du bist mein Assistent für die Wissenserfassung. Ich möchte einen JIRA-Export 
für unsere Knowledge Base erstellen.

**Aufgabe:**
Exportiere abgeschlossene JIRA-Tickets aus dem Projekt **[JIRA-Projektkey, z.B. "MUP"]** 
im Zeitraum **[von YYYY-MM-DD bis YYYY-MM-DD]**.

**Projektname:** [Projektname, z.B. "mup"]
**Repository für den Commit:** [z.B. "kernpunkt/mup-jira-memory"]

**Schritt 1 — Zeige mir zuerst nur die Liste der Tickets:**
Liste alle Tickets auf, die im Zeitraum auf "Done" oder "Closed" gesetzt wurden.
Zeige: Ticket-Key, Titel, Typ (Story/Bug/Task), Abschlussdatum.
Warte dann auf meine Bestätigung, welche Tickets exportiert werden sollen.

**Regeln für den Export (Schritt 2):**
- Nur Tickets, die ich in Schritt 1 bestätigt habe
- Übernehme die Ticket-Beschreibung unverändert (kein LLM-Text erfinden)
- Aus den Kommentaren: nur solche, die Lösungsansätze, Designentscheidungen oder 
  technische Begründungen dokumentieren — keine Status-Updates wie "erledigt" oder 
  "in Review"
- Keine laufenden oder abgebrochenen Tickets

**Format der Ausgabe:** Erstelle eine Markdown-Datei mit diesem Frontmatter:
---
typ: jira-export
quelle_typ: jira-export
verbindlichkeit: niedrig
status: abgeschlossen
projekt: [projektname]
jira_project_key: [KEY]
zeitraum_von: YYYY-MM-DD
zeitraum_bis: YYYY-MM-DD
erstellt_von: po-manuell
erstellt_am: [heutiges Datum]
---

**Vorgehensweise:**
1. Zeige mir die Ticket-Liste (Schritt 1)
2. Ich gebe dir Feedback, welche Tickets rein sollen
3. Du erstellst das Exportdokument und zeigst es mir
4. Nach meinem OK: committe als `jira/YYYY-MM/YYYY-MM-DD_[KEY]-export.md` 
   ins Repo **[repo-name]** auf den main-Branch
```

---

### Ablauf

1. **Prompt einfügen** und absenden
2. **Claude zeigt die Ticket-Liste** — du entscheidest:
   - Welche Tickets sind relevant?
   - Gibt es Tickets, die nicht in die KB sollen (z.B. interne Personalthemen)?
3. **Antworte mit den Ticket-Keys**, die exportiert werden sollen (oder "alle")
4. **Claude erstellt das Exportdokument** — lies es durch:
   - Sind die Kommentare sinnvoll ausgewählt?
   - Stimmen die Fakten?
5. **Bestätigen** → Claude committed

---

## Tipps

**Wie oft?**
- Teams-Zusammenfassungen: wöchentlich oder nach wichtigen Diskussionen
- JIRA-Exporte: zum Sprint-Ende oder monatlich

**Was tun bei schlechter Qualität?**  
Gib Claude konkretes Feedback: "Der Abschnitt zu Thema X fehlt" oder "Die Attribution bei Thread Y stimmt nicht — das war Maria, nicht Jan." Claude korrigiert und zeigt dir die neue Version.

**Was gehört nicht in die KB?**
- Persönliche Kritik oder HR-Themen
- Interne Gehalts- oder Budgetdiskussionen
- Noch nicht getroffene Entscheidungen ohne klaren Status

**Verbindlichkeit verstehen:**
| Typ | Verbindlichkeit | Bedeutung |
|-----|----------------|-----------|
| ADRs, formale Konzepte | `hoch` | Bindend, reviewed |
| Meeting-Protokolle | `mittel` | Abgestimmt |
| JIRA-Exporte | `niedrig` | Faktisch, aber kein Konsens-Dokument |
| Teams-Zusammenfassungen | `hinweis` | Orientierung, nicht abgestimmt |

KI-Agenten, die die KB abfragen, kennen diese Unterschiede und gewichten entsprechend.

---

## Was passiert danach?

Sobald Claude committed hat, läuft automatisch ein GitHub Action, der die Datei in die Knowledge Base (AWS Bedrock) einspielt. Nach ca. 1–2 Minuten ist der Inhalt durchsuchbar.
