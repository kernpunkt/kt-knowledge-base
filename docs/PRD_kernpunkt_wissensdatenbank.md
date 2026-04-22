# PRD: Zentrale Wissensdatenbank auf Basis von AWS Bedrock
**kernpunkt GmbH & Co. KG**

| | |
|---|---|
| **Status** | Draft v0.3 |
| **Erstellt am** | 16. April 2026 |
| **Erstellt von** | Jan Eickmann |
| **Letzte Änderung** | 22. April 2026 |

---

## Inhaltsverzeichnis

1. [Projektziel & Hintergrund](#1-projektziel--hintergrund)
2. [Stakeholder & Rollen](#2-stakeholder--rollen)
3. [Anforderungen](#3-anforderungen)
4. [Use Cases](#4-use-cases)
5. [Technische Architektur](#5-technische-architektur)
6. [Datenquellen & Dokumenttypen](#6-datenquellen--dokumenttypen)
7. [Nicht im Scope (Out of Scope)](#7-nicht-im-scope-out-of-scope)
8. [Offene Fragen & Annahmen](#8-offene-fragen--annahmen)
9. [Glossar](#9-glossar)

---

## 1. Projektziel & Hintergrund

### 1.1 Projektziel

**Primärziel**: Projektwissen für Projektmitglieder und deren KI-Agenten verfügbar machen.

Konkret bedeutet das: Jedes Projektmitglied – und jeder KI-Agent, der in einem Projekt-Kontext arbeitet – soll jederzeit strukturiert und semantisch auf die relevante Dokumentation des eigenen Projekts zugreifen können, ohne manuell in Repositories suchen zu müssen.

**Sekundärziel**: Projektübergreifender Zugriff auf Projektwissen.

Wissen aus einem Projekt soll auch in anderen Projekten nutzbar sein – z.B. um Architekturentscheidungen aus vergangenen Projekten auf neue anzuwenden oder Best Practices über Projektgrenzen hinweg zu teilen.

**Tertiärziel**: Wartungsarmer Betrieb.

Die Lösung soll im laufenden Betrieb keinen oder minimalen technischen Eingriff erfordern. Neue Projekte und Dokumente sollen ohne manuelle Konfiguration in die Wissensdatenbank einfließen. Managed Services (AWS Bedrock, S3) werden bewusst gegenüber selbst betriebenem Compute bevorzugt.

Technisches Fundament ist eine **zentrale Wissensdatenbank auf Basis von AWS Bedrock Knowledge Bases**, die die kernpunkt-Projektdokumentation – insbesondere fachliche und technische Konzepte sowie Architekturentscheidungen aus dem Bereich E-Commerce und Webentwicklung – konsolidiert und semantisch abrufbar macht.

### 1.2 Hintergrund & Motivation

kernpunkt betreut eine Vielzahl von E-Commerce- und Webprojekten. Das dabei entstehende Wissen – Architekturentscheidungen, Konzepte, technische Spezifikationen, Best Practices – ist aktuell **fragmentiert** in verschiedenen GitHub-Repositories verteilt und damit für automatisierte Systeme und KI-Agenten nur schwer zugänglich.

Folgende Probleme sollen adressiert werden:

- **Wissenssilos**: Projektrelevantes Wissen liegt unstrukturiert in Repositories und ist ohne manuelle Suche nicht auffindbar.
- **Fehlende KI-Nutzbarkeit**: Existierende Dokumentation ist nicht in einem Format, das KI-Agenten direkt abfragen können.
- **Hoher Onboarding-Aufwand**: Neue Teammitglieder sowie Agenten können nicht effizient auf bestehendes Projektwissen zugreifen.
- **Keine Wiederverwendung von Architekturwissen**: Einmal getroffene Entscheidungen (ADRs) werden in neuen Projekten nicht systematisch berücksichtigt.

### 1.3 Erfolgskriterien

| Ziel | Kriterium | Messung |
|---|---|---|
| **Primärziel** | Projektmitglieder und deren KI-Agenten können projektrelevante Dokumentation semantisch abrufen | Manuelle Abnahme anhand definierter Testfragen je Pilotprojekt |
| **Primärziel** | Retrieval-Qualität: ≥ 80 % der Anfragen liefern thematisch relevante Ergebnisse | Internes Evaluierungsset (Frage-Antwort-Paare) |
| **Sekundärziel** | Projektübergreifendes Retrieval funktioniert ohne zusätzliche Konfiguration durch den Nutzer | Testfragen, die Wissen aus ≥ 2 Projekten kombinieren |
| **Betrieb** | Neue oder geänderte Dokumente sind innerhalb von 1 Stunde in der Wissensdatenbank verfügbar | Automatisiertes Monitoring der Ingestion-Pipeline |
| **Skalierung** | Die Lösung ist ohne Architekturumbau auf alle bestehenden und zukünftigen kernpunkt-Projekte erweiterbar | Architekturbewertung bei > 20 Repositories |
| **Wartbarkeit** | Ein neues Repository kann ohne manuellen Eingriff ins System aufgenommen werden | Onboarding eines neuen Repos erfordert ausschließlich Konfiguration im Repository selbst (z.B. GitHub Action) |

---

## 2. Stakeholder & Rollen

### 2.1 Stakeholder-Übersicht

| Rolle | Person / Team | Interesse / Verantwortung |
|---|---|---|
| **Product Owner** | Jan Eickmann | Gesamtverantwortung, Priorisierung, Abnahme |
| **Technischer Architekt** | Engineering-Team kernpunkt | Entwurf und Umsetzung der technischen Architektur |
| **Wissensverantwortliche** (Knowledge Owners) | Tech Leads der Projektteams | Qualitätssicherung der Dokumentation in den Repositories |
| **Konsumenten – Dev-Assistent** | Entwicklerinnen und Entwickler | Nutzen den Agenten für technische Entscheidungsfindung |
| **Konsumenten – PM-Agent** | Projektleitungen | Nutzen den Agenten für Projektplanung und Onboarding |
| **Konsumenten – Konzept/UX-Agent** | UX-Designer, Konzepter | Nutzen den Agenten für Recherche zu bestehenden UX-Entscheidungen, Designkonzepten und Interaktionsmustern |
| **Zukünftige Agenten** | Intern / Extern | Generisch über API-Layer abrufbar |

### 2.2 Rollenmodell

| Rolle | Beschreibung |
|---|---|
| **Knowledge Ingester** | Automatisierter Prozess; liest Repositories, schreibt in die Wissensdatenbank |
| **Knowledge Consumer** | KI-Agenten, die die Wissensdatenbank per Retrieval-API abfragen |
| **Knowledge Owner** | Menschliche Verantwortliche, die Qualität und Vollständigkeit der Quelldokumente sichern |
| **Administrator** | Pflege der AWS-Infrastruktur, Monitoring, Zugriffskontrolle |

---

## 3. Anforderungen

### 3.1 Funktionale Anforderungen

#### F-01: Dokumenten-Ingestion aus GitHub

Das System muss Dokumente aus definierten GitHub-Repositories aufbereiten und in die Wissensdatenbank überführen.

- **Unterstützte Formate**: Markdown (`.md`) sowie gängige Bildformate (`.png`, `.jpg`, `.svg`) für eingebettete Diagramme und Mockups
- **Ingestion-Trigger**: Per Post-Commit-Hook (z.B. GitHub Action) werden geänderte Dateien aus dem Hauptbranch in einen dedizierten **Amazon S3-Bucket** synchronisiert. AWS Bedrock Knowledge Base liest die Dokumente aus diesem S3-Bucket. Wie genau die Synchronisierung implementiert wird (GitHub Action, AWS CodePipeline o.Ä.), ist Teil des technischen Designs und nicht Bestandteil dieser Anforderung.
- **Chunking-Strategie**: Semantisches Chunking bevorzugt; Fallback auf Fixed-Size-Chunking

#### F-02: Semantische Suche (Retrieval)

KI-Agenten müssen Inhalte der Wissensdatenbank mittels natürlichsprachiger Abfragen semantisch durchsuchen können.

- Retrieval über Bedrock Knowledge Base API (`Retrieve`) – die Antwortgenerierung obliegt dem jeweiligen Agenten
- Top-K konfigurierbar (Standard: K=5)
- Filterung nach Metadaten (Projektzugehörigkeit, Dokumenttyp, Datum)

#### F-03: Metadaten-Anreicherung

Jedes Dokument wird beim Ingestion-Prozess mit Metadaten versehen. Die Metadaten setzen sich aus zwei Quellen zusammen:

**Technische Metadaten** (werden automatisch beim Sync ermittelt):

- `source_repo`: Name des GitHub-Repositories
- `last_updated`: Timestamp der letzten Änderung
- `last_editor`: Letzter Commit-Author

**Frontmatter-Metadaten** (werden dynamisch aus dem Dokument ausgelesen):

Markdown-Dokumente können Obsidian-kompatibles YAML-Frontmatter enthalten. Alle darin definierten Felder werden automatisch als Metadaten übernommen und stehen für die Filterung im Retrieval zur Verfügung. Das Metadatenschema ist damit nicht fest vorgegeben, sondern ergibt sich aus den konkreten Dokumenten.

Beispiel-Frontmatter:
```yaml
---
projekt: mein-kundenprojekt
typ: architekturentscheidung
status: entschieden
tags: [shopware, caching, performance]
---
```

> **Hinweis**: Eine projektweite Konvention für Frontmatter-Felder ist empfehlenswert, um konsistente Filterbarkeit sicherzustellen. Die Definition dieser Konvention ist nicht Bestandteil dieser Anforderung.

#### F-04: API-Zugang für Agenten

Die Wissensdatenbank stellt einen einheitlichen Zugangs-Layer bereit, über den alle KI-Agenten auf die gesamte Knowledge Base zugreifen können. Die Einschränkung auf bestimmte Projekte oder Repositories erfolgt nicht auf Zugangsebene, sondern über Metadaten-Filter in der Abfrage (siehe F-02, F-03).

- **Authentifizierung**: AWS IAM Roles (Role-based Access)
- **Interface**: AWS Bedrock Knowledge Base API (`Retrieve`) via REST/SDK
- **Antwortformat**: JSON mit Quellenangabe (Dokument, Repository, Chunk)

**Zugang über MCP**: Als Alternative zur direkten API-Integration steht ein **zentral gehosteter MCP-Server** bereit. Dieser ist als AWS Lambda-Funktion mit Lambda Function URL implementiert und exponiert die Wissensdatenbank als MCP-Tool (`retrieve_from_knowledge_bases`). MCP-kompatible Clients (z.B. Claude Desktop, Claude Code) können sich direkt damit verbinden – ohne eigene API-Integration oder lokale Tooling-Installation.

- **Authentifizierung**: API-Key via `Authorization: Bearer`-Header (Key wird automatisch bei Deployment generiert und in AWS Secrets Manager gespeichert)
- **Skalierung**: Scale-to-zero – keine Kosten im Leerlauf
- **Protokoll**: MCP Streamable HTTP Transport (JSON-RPC 2.0 über HTTP POST)

Dieser Zugangsweg ist besonders relevant für den Dev-Assistenten und den Konzept/UX-Agenten, die typischerweise in MCP-fähigen Umgebungen betrieben werden.

#### F-05: Quellenangabe im Retrieval-Ergebnis

Jede Antwort des Retrieval-Systems muss die Herkunft des genutzten Wissens transparent ausweisen:

- Repository-Name und Pfad zur Quelldatei
- Relevanz-Score des Chunks

### 3.2 Nicht-funktionale Anforderungen

| ID | Kategorie | Anforderung |
|---|---|---|
| NF-01 | **Verfügbarkeit** | ≥ 99,5 % Uptime (SLA durch AWS Bedrock) |
| NF-02 | **Latenz** | Retrieval-Anfragen werden in < 3 Sekunden beantwortet (p95) |
| NF-03 | **Skalierbarkeit** | Das System muss ohne Architekturumbau auf > 100 Repositories erweiterbar sein |
| NF-04 | **Sicherheit** | Zugriff ausschließlich über IAM; keine öffentliche API; Daten verschlüsselt at rest und in transit |
| NF-05 | **Datenkonsistenz** | Änderungen in Repositories werden innerhalb von 1 Stunde in der Wissensdatenbank reflektiert |
| NF-06 | **Kosteneffizienz** | Architektur nutzt Serverless-Komponenten zur Kostenkontrolle (kein dauerhafter Compute) |

---

## 4. Use Cases

> **Lesehinweis**: UC-01 bis UC-04 adressieren das Primärziel (projektspezifischer Zugriff). UC-05 und UC-06 adressieren das Sekundärziel (projektübergreifender Zugriff). UC-07 beschreibt den technischen Betriebsfall.

---

### UC-01: PM-Agent unterstützt beim Projekt-Onboarding

**Akteur**: Projekt-Management-Agent

**Ablauf**:
1. Ein neues Teammitglied tritt einem Kundenprojekt bei.
2. Der PM-Agent fragt die Wissensdatenbank gefiltert nach dem jeweiligen Projekt: *„Welche technischen und fachlichen Rahmenbedingungen gelten für dieses Projekt?"*
3. Die Wissensdatenbank liefert Projektkonzept, Architekturübersicht und relevante Entscheidungen aus dem Projekt-Repository.
4. Der PM-Agent erstellt daraus eine Onboarding-Zusammenfassung.

**Erwartetes Ergebnis**: Kontextreiche Zusammenfassung aus mehreren Quelldokumenten des Projekts.

---

### UC-02: Dev-Assistent fragt projektspezifische Architekturentscheidungen ab

**Akteur**: Interner Dev-Assistent (KI-Agent)

**Ablauf**:
1. Ein Entwickler arbeitet an einem konkreten Projekt und fragt den Dev-Assistenten: *„Welche Architekturentscheidungen wurden in diesem Projekt zum Thema Caching getroffen?"*
2. Der Assistent formuliert eine semantische Abfrage an die Wissensdatenbank, gefiltert auf das aktuelle Projekt-Repository.
3. Die Wissensdatenbank liefert relevante Chunks aus ADRs und technischen Konzepten des Projekts.
4. Der Dev-Assistent synthetisiert eine Antwort mit Quellenangaben.

**Erwartetes Ergebnis**: Antwort mit Bezug auf konkrete Dokumente aus dem Projekt-Repository.

---

### UC-03: Konzept/UX-Agent fragt bestehende Konzeptentscheidungen ab

**Akteur**: Konzept/UX-Agent

**Ablauf**:
1. Ein Konzepter beginnt mit der Erstellung eines neuen Konzepts (z.B. ein Kundenkonto-Bereich für einen E-Commerce-Kunden).
2. Der Konzept/UX-Agent fragt die Wissensdatenbank projektspezifisch: *„Welche konzeptionellen Entscheidungen wurden in diesem Projekt bereits zum Thema Kundenkonto getroffen?"*
3. Die Wissensdatenbank liefert relevante Konzeptdokumente, Designentscheidungen und Begründungen aus dem Projekt-Repository.
4. Der Konzepter kann auf dieser Basis konsistent mit bestehenden Entscheidungen weiterarbeiten – oder bestehende Entscheidungen bewusst revidieren und dies dokumentieren.

**Erwartetes Ergebnis**: Übersicht bereits getroffener konzeptioneller Entscheidungen im Projekt als Grundlage für die neue Konzeptarbeit – verhindert Widersprüche und Doppelarbeit.

---

### UC-04: Aus Konzept werden Umsetzungsstories abgeleitet

**Akteur**: PM-Agent oder Dev-Assistent

**Ablauf**:
1. Ein Konzeptdokument (z.B. ein Fachkonzept für eine neue Checkout-Funktion) liegt im Projekt-Repository.
2. Der Agent ruft das Konzept aus der Wissensdatenbank ab und liest es im Kontext weiterer projektrelevanter Dokumente (z.B. bestehende Architekturentscheidungen, technische Rahmenbedingungen).
3. Der Agent leitet aus dem Konzept konkrete Umsetzungsstories oder Tickets ab – unter Berücksichtigung des bekannten technischen Kontexts des Projekts.
4. Die generierten Stories werden dem Nutzer zur Überprüfung und Anpassung vorgelegt.

**Erwartetes Ergebnis**: Strukturierte Umsetzungsstories (z.B. im Format „Als [Rolle] möchte ich [Funktion], damit [Nutzen]") mit Referenz auf das zugrunde liegende Konzeptdokument.

**Hinweis**: Die Qualität der abgeleiteten Stories hängt direkt von der Vollständigkeit und Struktur der Konzeptdokumentation im Repository ab.

---

### UC-05: Konzept/UX-Agent recherchiert UX-Entscheidungen projektübergreifend

**Akteur**: Konzept/UX-Agent

**Ablauf**:
1. Ein Konzepter oder UX-Designer beginnt mit der Konzeption eines neuen Features (z.B. Checkout-Optimierung für einen E-Commerce-Kunden).
2. Der Konzept/UX-Agent fragt die Wissensdatenbank projektübergreifend: *„Welche UX-Konzepte und Interaktionsmuster haben wir in bisherigen Projekten für den Checkout-Prozess entwickelt?"*
3. Die Wissensdatenbank liefert relevante Konzeptdokumente, UX-Entscheidungen und Designbegründungen aus mehreren Repositories.
4. Der Agent synthetisiert eine Übersicht bestehender Lösungsansätze als Grundlage für das neue Konzept.

**Erwartetes Ergebnis**: Zusammenfassung relevanter UX-Entscheidungen und Konzepte mit Quellenangaben als Recherche-Basis für neue Konzeptarbeit.

---

### UC-06: Dev-Assistent sucht projektübergreifend nach Lösungsansätzen

**Akteur**: Interner Dev-Assistent (KI-Agent)

**Ablauf**:
1. Ein Entwickler steht vor einem technischen Problem und fragt projektübergreifend: *„Wie haben wir in bisherigen Projekten das Caching-Layer für Shopware gelöst?"*
2. Der Assistent formuliert eine semantische Abfrage ohne Projektfilter.
3. Die Wissensdatenbank liefert relevante Chunks aus ADRs und technischen Konzepten über alle Repositories hinweg.
4. Der Dev-Assistent synthetisiert eine Antwort mit Quellenangaben je Projekt.

**Erwartetes Ergebnis**: Antwort mit Bezug auf Lösungsansätze aus mindestens einem, idealerweise mehreren Projekt-Repositories.

---

### UC-07: Automatische Aktualisierung bei Dokumentänderung

**Akteur**: GitHub Action / CI/CD-Pipeline

**Ablauf**:
1. Ein Tech Lead merged ein neues ADR in den Hauptbranch eines Repositories.
2. Der Post-Commit-Hook (GitHub Action) synchronisiert die geänderte Datei in den S3-Bucket.
3. AWS Bedrock liest das Dokument, chunkt es, erstellt Embeddings und schreibt es in die Vektordatenbank.
4. Die Wissensdatenbank ist innerhalb von < 1 Stunde aktualisiert.

**Erwartetes Ergebnis**: Neues Wissen ist zeitnah für alle Agenten abrufbar.

---

## 5. Technische Architektur

### 5.1 Überblick

```
GitHub Repositories
        │
        │ (Post-Commit-Hook / GitHub Action)
        ▼
┌─────────────────────────┐
│       Amazon S3         │
│  (.md + Bilddateien)    │
└────────────┬────────────┘
             │
             ▼
┌─────────────────────────────────────────┐
│        AWS Bedrock Knowledge Base        │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │  Embedding Model                 │   │
│  │  (Amazon Titan Embeddings v2)    │   │
│  └──────────────────────────────────┘   │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │  Vector Store                    │   │
│  │  (Amazon S3 Vectors)             │   │
│  └──────────────────────────────────┘   │
└─────────────────┬───────────────────────┘
                  │
                  │ Retrieve API
                  ▼
┌─────────────────────────────────────────┐
│              Agenten-Layer               │
│                                         │
│  ┌───────────────┐  ┌────────────────┐  │
│  │ Dev-Assistent │  │   PM-Agent     │  │
│  └───────────────┘  └────────────────┘  │
│                                         │
│  ┌───────────────────┐                  │
│  │ Konzept/UX-Agent  │                  │
│  └───────────────────┘                  │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │  Generische Agenten (via API)    │   │
│  └──────────────────────────────────┘   │
└─────────────────────────────────────────┘
```

### 5.2 Komponenten im Detail

#### 5.2.1 Ingestion Pipeline

| Komponente | Technologie | Zweck |
|---|---|---|
| **Trigger** | Post-Commit-Hook (z.B. GitHub Action) | Ausgelöst bei Push/Merge in Hauptbranch |
| **Sync** | GitHub Action / AWS CLI | Geänderte `.md`- und Bilddateien in S3-Bucket synchronisieren |
| **Staging Storage** | Amazon S3 (dedizierter Bucket) | Quelldokumente für Bedrock Knowledge Base |
| **Vorverarbeitung** | AWS Bedrock (nativ) | Chunking, Embedding, Indexierung |

#### 5.2.2 AWS Bedrock Knowledge Base

| Komponente | Konfiguration |
|---|---|
| **Data Source** | S3-Bucket (automatischer Sync) |
| **Chunking** | Semantic Chunking (Bedrock-native) |
| **Embedding Model** | `amazon.titan-embed-text-v2:0` |
| **Vector Store** | Amazon S3 Vectors (Index-Typ: float32, 1024 Dimensionen, Cosine Distance) |
| **Foundation Model** | Nicht Teil der Knowledge Base – Antwortgenerierung obliegt dem jeweiligen Agenten |

#### 5.2.3 Zugangs-Layer für Agenten

- **API**: AWS Bedrock Knowledge Base API (`bedrock-agent-runtime`) – ausschließlich `Retrieve`
- **MCP**: Zentral gehosteter MCP-Server (AWS Lambda + Function URL) – siehe F-04
- **Authentifizierung API**: AWS IAM Roles (Least-Privilege-Prinzip)
- **Authentifizierung MCP**: API-Key via `Authorization: Bearer`-Header
- **Metadaten-Filter**: Agenten können nach technischen Metadaten (`source_repo`) sowie beliebigen Frontmatter-Feldern filtern

#### 5.2.4 MCP-Server

| Komponente | Konfiguration |
|---|---|
| **Laufzeit** | AWS Lambda (Python 3.12) |
| **Zugang** | Lambda Function URL (HTTPS) |
| **Authentifizierung** | API-Key in AWS Secrets Manager, validiert im Handler |
| **Protokoll** | MCP Streamable HTTP Transport (JSON-RPC 2.0 via HTTP POST) |
| **Tool** | `retrieve_from_knowledge_bases` mit optionalem `source_repo`-Filter |
| **Skalierung** | Scale-to-zero (keine Kosten im Leerlauf) |

### 5.3 Infrastruktur & Deployment

Die gesamte Infrastruktur wird als deploybare **AWS CDK App (TypeScript)** definiert und versioniert. Ziel ist ein einziger `cdk deploy`-Befehl, der die vollständige Umgebung provisioniert.

| Aspekt | Entscheidung |
|---|---|
| **IaC** | AWS CDK (TypeScript) |
| **CI/CD** | GitHub Actions für Infrastruktur-Deployment |
| **Umgebungen** | `dev`, `production` (separate CDK Stacks) |
| **Region** | `eu-central-1` (Frankfurt) |
| **Logging & Monitoring** | AWS CloudWatch (Logs, Metriken, Alarme) |
| **Secrets Management** | AWS Secrets Manager (GitHub Token, etc.) |

Das Projekt liefert die **Infrastruktur und ein wiederverwendbares GitHub Action Script**. Welche Repositories die Wissensdatenbank nutzen, ist nicht Teil dieses Projekts – ein Repository nimmt sich selbst auf, indem es das bereitgestellte Script einbindet.

Der CDK-Stack umfasst mindestens:

- S3-Bucket (Dokumenten-Staging, inkl. Bucket-Policy und Versionierung)
- AWS Bedrock Knowledge Base (inkl. Data Source-Konfiguration auf S3)
- Amazon S3 Vectors (Vector Bucket + Index für die Vektorsuche)
- IAM Roles für Agenten-Zugriff (Least-Privilege)
- IAM Role für den S3-Sync aus GitHub Actions
- MCP-Server (Lambda-Funktion + Function URL + API-Key in Secrets Manager)
- CloudWatch Log Groups und Alarme

### 5.4 Datenfluss im Retrieval

```
Agent-Anfrage (natürliche Sprache)
         │
         ▼
Bedrock Knowledge Base API
         │
         ▼
Anfrage wird eingebettet (Titan Embeddings)
         │
         ▼
Vektorsuche in Amazon S3 Vectors
         │
         ▼
Top-K relevante Chunks + Metadaten
         │
         └──► Chunks + Metadaten direkt zurück (Retrieve)
```

---

## 6. Datenquellen & Dokumenttypen

### 6.1 Datenquellen

**Primärquelle**: GitHub-Repositories der kernpunkt GmbH

| Kriterium | Beschreibung |
|---|---|
| **Repository-Auswahl** | Ein Repository wird durch Einrichtung der GitHub Action im Repo selbst aufgenommen – kein zentraler Eingriff erforderlich |
| **Branch** | Nur `main` / `master` Branch (konfigurierbar) |
| **Dateitypen** | `.md`, `.png`, `.jpg`, `.svg` |
| **Ausschluss** | Code-Dateien (`.js`, `.ts`, `.php`, etc.), Build-Artefakte, `.env`-Dateien |

### 6.2 Priorisierte Dokumenttypen

| Typ | Beschreibung | Priorität |
|---|---|---|
| **Architecture Decision Records (ADRs)** | Strukturierte Entscheidungsdokumente (z.B. nach MADR-Format) | Hoch |
| **Technische Konzepte** | Architekturübersichten, Systemdesign-Dokumente | Hoch |
| **Fachliche Konzepte** | Business-Anforderungen, Prozessdokumentation | Hoch |
| **UX-Konzepte** | Interaktionsmuster, Designentscheidungen, Wireframe-Beschreibungen | Hoch |
| **Projektdokumentation** | README, Setup-Guides, Deployment-Dokumentation | Mittel |
| **Meeting-Protokolle** | Entscheidungsrelevante Protokolle | Niedrig |

---

## 7. Nicht im Scope (Out of Scope)

Folgende Themen sind **explizit nicht** Teil dieses Projekts:

- **Öffentlicher Zugriff**: Die Wissensdatenbank ist rein intern; keine öffentliche API.
- **Echtzeit-Sync** (< 1 Minute): Änderungen werden mit einem Delay von max. 1 Stunde übernommen.
- **Code-Analyse**: Quellcode aus Repositories wird nicht eingebettet oder analysiert – nur Dokumentation.
- **Confluence / SharePoint / Google Drive**: Nur GitHub ist im initialen Scope.
- **Videos**: Videoinhalte werden nicht indexiert.
- **Benutzerverwaltung / UI**: Kein Frontend; Zugriff ausschließlich programmatisch über API.

---

## 8. Offene Fragen & Annahmen

### 8.1 Offene Fragen

| # | Frage | Verantwortlich | Fälligkeit |
|---|---|---|---|
| 1 | Wie wird die Qualität der Retrieval-Ergebnisse gemessen und wer führt Evaluierungen durch? | Engineering | TBD |
| 2 | Welche AWS-Account-Struktur liegt vor (Prod-Account, Dev-Account separat)? | Infra-Team | TBD |

### 8.2 Annahmen

- Es besteht bereits ein AWS-Account mit entsprechenden Berechtigungen für Bedrock.
- Die AWS-Region ist **`eu-central-1`** (Frankfurt). AWS Bedrock Knowledge Bases muss in dieser Region verfügbar sein.
- GitHub-Repositories sind über einen Service Account oder GitHub App mit Leserechten erreichbar.
- Dokumente in den Repositories sind überwiegend auf Deutsch oder Englisch verfasst.
- Das Team hat grundlegende AWS-Kenntnisse und Zugriff auf die AWS-Konsole.

---

## 9. Glossar

| Begriff | Definition |
|---|---|
| **ADR** | Architecture Decision Record – strukturiertes Dokument zur Dokumentation von Architekturentscheidungen |
| **Bedrock Knowledge Base** | AWS-Service für die Erstellung und Verwaltung von RAG-fähigen Wissensdatenbanken |
| **Chunking** | Aufteilung von Dokumenten in kleinere Abschnitte für das Embedding |
| **Embedding** | Vektorielle Repräsentation von Text für semantische Suche |
| **Ingestion** | Prozess des Einlesens, Aufbereitens und Einspeisens von Dokumenten in die Wissensdatenbank |
| **MCP** | Model Context Protocol – offenes Protokoll zur Integration von Tools und Datenquellen in KI-Agenten |
| **MCP-Server** | Zentral gehosteter Lambda-basierter Server, der die Wissensdatenbank als MCP-Tool exponiert |
| **RAG** | Retrieval-Augmented Generation – KI-Ansatz, der LLMs mit externer Wissensbasis anreichert |
| **Retrieval** | Abruf semantisch relevanter Dokumente aus der Vektordatenbank |
| **Vector Store** | Datenbank zur Speicherung und Abfrage von Embedding-Vektoren (hier: Amazon S3 Vectors) |

---

*Dieses Dokument ist ein lebendes Artefakt und wird im Laufe des Projekts kontinuierlich aktualisiert.*
