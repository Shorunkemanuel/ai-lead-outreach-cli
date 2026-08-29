# V1 Architecture

## Objective

Keep the application as a single Python script while preserving clean logical boundaries so V2 can be modularized without rewriting the core behavior.

## System flow

```text
CSV leads
   ↓
Import + normalization
   ↓
Validation + duplicate detection
   ↓
Deterministic lead scoring
   ↓
Local Ollama analysis
   ↓
Structured AI result validation
   ↓
Message draft
   ↓
Human review
   ├── Edit
   ├── Regenerate
   ├── Skip
   └── Approve
          ↓
   Messaging provider
          ↓
   SQLite outreach history
```

## Components inside `lead_cli.py`

1. Configuration — load defaults and local configuration.
2. Database — initialize SQLite and perform persistence.
3. Lead repository — import, normalize, deduplicate, query and update leads.
4. Scoring — deterministic, explainable lead score.
5. Ollama client — local HTTP client with timeout/error handling.
6. AI service — prompt construction and structured response validation.
7. Message service — draft, edit and review workflow.
8. Provider interface — provider-neutral send operation.
9. Outreach service — daily limits, duplicate protection and delivery logging.
10. CLI — commands and interactive review loop.

## Persistence

SQLite is the source of truth for application state. JSON is not used for operational history.

Core entities:

- `leads`
- `outreach`
- `daily_usage`

The schema should retain original lead data and preserve both AI-generated and user-edited message versions.

## AI boundary

The AI is advisory. It receives explicit lead data and returns structured analysis plus a draft. It must not invent evidence, contact details, company facts or claims about a website that was not actually provided/analyzed.

## Messaging boundary

The application must not couple business logic to a specific WhatsApp implementation. A provider abstraction allows a compliant provider to be selected later. V1 defaults to dry-run and human approval.

## Security boundary

Secrets are supplied through environment variables/local configuration and are never committed. AI output is treated as untrusted data and must not be executed as shell commands.

## V2 migration path

If V1 grows beyond a manageable single file, extract the logical sections into modules without changing their public behavior. Likely future modules: `db`, `ai`, `providers`, `campaigns`, `cli`, and `services`.
