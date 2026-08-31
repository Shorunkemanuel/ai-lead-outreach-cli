# M8 — Statistics & CLI polish

## Scope

M8 adds a read-only reporting layer over the existing M1-M7 SQLite workflow. It does not alter lead qualification, AI generation, human approval, messaging providers, or M7 safety decisions.

## Command

```bash
python3 m8_stats.py
```

Useful options:

```bash
python3 m8_stats.py --section leads
python3 m8_stats.py --section drafts
python3 m8_stats.py --section outreach
python3 m8_stats.py --limit 30
python3 m8_stats.py --json
python3 m8_stats.py --help
python3 m8_stats.py --version
```

## Reported data

- Total leads and lead status counts.
- Qualification counts by priority, scored-lead count, and average score.
- Outreach-draft counts by status.
- Outreach sent today and remaining against the configured report limit.
- Queue counts by status.
- Today's sent messages grouped by channel and provider.

The reporter is intentionally read-only. It does not queue, approve, send, suppress, retry, or otherwise mutate outreach state.

## M8 acceptance

M8 is complete when the statistics module and tests are present, the report is deterministic for the same database state, JSON output is valid, CLI help/options are usable, and the existing M1-M7 test suite remains green.
