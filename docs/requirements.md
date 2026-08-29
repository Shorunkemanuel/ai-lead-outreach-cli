# V1 Requirements

## Functional requirements

- Import lead records from CSV.
- Validate required fields and normalize values.
- Deduplicate leads using stable contact/company identifiers.
- Store lead records in SQLite.
- Calculate an explainable 0–100 lead score.
- Send explicit lead data to a local Ollama endpoint.
- Require structured AI output.
- Validate AI output before it enters the workflow.
- Generate concise personalized outreach drafts.
- Support professional, conversational, direct, problem-focused and value-focused styles.
- Provide human review with approve, edit, regenerate and skip actions.
- Prevent duplicate outreach by default.
- Enforce a configurable daily send limit; default 10.
- Support dry-run mode that cannot send messages.
- Send only explicitly approved messages through the configured provider.
- Record generated, edited, approved, sent and failed states.
- Provide basic statistics.
- Continue processing other leads when one lead fails.

## Non-functional requirements

- Python 3.11+.
- Standard library first; keep dependencies minimal.
- SQLite for persistence.
- Local-first AI through Ollama.
- No credentials committed to Git.
- No arbitrary execution of AI-generated content.
- Clear terminal errors and actionable recovery messages.
- Deterministic behavior where possible.
- Safe interruption: progress already committed to SQLite must remain intact.

## Safety and outreach controls

Human approval is the default gate before real delivery. Dry-run is the default during development. The system must support suppression/do-not-contact state and must not claim that an arbitrary daily limit makes outreach legally compliant. Users remain responsible for provider terms, consent/legitimate-interest requirements, privacy obligations and applicable anti-spam laws.

## Definition of done

A user can import an Apollo-style CSV, inspect valid leads, score them, generate local-AI drafts, review/edit/approve them, run in dry-run mode, and persist the complete workflow in SQLite without duplicate sends or secret leakage.
