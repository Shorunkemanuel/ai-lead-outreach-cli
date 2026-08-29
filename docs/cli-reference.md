# CLI Reference — V1

The primary executable is `lead_cli.py`.

## Commands

```bash
python lead_cli.py
python lead_cli.py import data/leads.csv
python lead_cli.py analyze
python lead_cli.py review
python lead_cli.py stats
python lead_cli.py run --dry-run
python lead_cli.py send
```

## Intended behavior

### `python lead_cli.py`

Open the interactive CLI dashboard and expose the main workflow.

### `import`

Validate and import a CSV into SQLite. Existing records must be deduplicated rather than blindly inserted.

### `analyze`

Select eligible leads and generate local AI analysis/drafts. Analysis must not send messages.

### `review`

Present pending drafts. The user can approve, edit, regenerate or skip.

### `stats`

Show lead, outreach and daily-limit statistics.

### `run --dry-run`

Run the complete processing workflow without external message delivery.

### `send`

Send only previously approved messages through the configured provider, subject to duplicate protection and the daily limit.

## Exit behavior

- `0` success
- non-zero on configuration, database or fatal operational errors
- per-lead failures should be logged and should not abort unrelated leads
