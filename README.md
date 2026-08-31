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
- Statistics and CLI reporting
- Secure configuration without secrets in source control

## Milestones

- M1 — Lead ingestion & database
- M2 — Lead scoring & qualification
- M3 — Ollama AI integration
- M4 — AI message generation
- M5 — Human review workflow
- M6 — Messaging provider
- M7 — Daily limits & duplicate safety
- M8 — Statistics & CLI polish
- M9 — Full V1 testing

## M8 reporting

M8 adds a read-only statistics command over the existing M1-M7 SQLite data:

```bash
python3 m8_stats.py
python3 m8_stats.py --section leads
python3 m8_stats.py --section drafts
python3 m8_stats.py --section outreach
python3 m8_stats.py --json
python3 m8_stats.py --help
```

The reporter does not approve, queue, send, suppress, retry, or otherwise mutate outreach state.

## Repository structure

```text
ai-lead-outreach-cli/
├── lead_cli.py
├── m4_outreach.py
├── m8_stats.py
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
│   ├── ai-prompt-spec.md
│   └── m8-statistics-cli.md
└── tests/
    ├── README.md
    └── test_m8_stats.py
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

Start with the documentation in `docs/requirements.md`, `docs/architecture.md`, and `docs/m8-statistics-cli.md`. The application is intentionally designed as a single Python script for V1; M8's reporting module is read-only so the existing M1-M7 workflow remains unchanged.
