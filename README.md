# AI Lead Outreach CLI

A lightweight, local-first Python CLI for qualifying business leads, using local AI to analyze opportunities and draft personalized outreach, then routing approved messages through a configurable messaging provider.

## V1 philosophy

**AI analyzes → AI drafts → human reviews → approved message is sent → result is logged.**

V1 intentionally stays small: one Python application script, SQLite persistence, CSV import, Ollama for local AI, and a provider abstraction for messaging.

## Status

🚧 Version 1 foundation — implementation follows the documented requirements.

## Planned V1 capabilities

- CSV lead import and validation
- Duplicate detection
- Deterministic lead scoring
- Local Ollama analysis and message generation
- Structured AI output validation
- Human approve/edit/regenerate/skip workflow
- Dry-run mode
- Daily outreach limit
- SQLite outreach history
- Messaging-provider abstraction
- Basic statistics
- Secure configuration without secrets in source control

## Repository structure

```text
ai-lead-outreach-cli/
├── lead_cli.py
├── README.md
├── LICENSE
├── .gitignore
├── .env.example
├── config.example.json
├── data/
│   └── leads.example.csv
├── docs/
│   ├── architecture.md
│   ├── requirements.md
│   ├── cli-reference.md
│   └── ai-prompt-spec.md
└── tests/
    └── README.md
```

## Local-first requirements

- Python 3.11+
- SQLite (included with Python)
- Ollama installed locally for AI features
- A local Ollama model configured in `config.json`
- A supported messaging provider only when real sending is enabled

## Safety defaults

- Dry-run during development
- Human approval before sending
- Duplicate protection
- Configurable daily limit
- Do-not-contact support in the data model
- API secrets kept outside source control
- AI must not invent evidence about a prospect

## Development

Start with the documentation in `docs/requirements.md` and `docs/architecture.md`. The application is intentionally designed as a single Python script for V1; logical separation is maintained through functions/classes rather than premature multi-package decomposition.
