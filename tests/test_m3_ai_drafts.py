import importlib.util
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lead_cli_m3", ROOT / "lead_cli.py")
lead_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lead_cli
assert SPEC.loader is not None
SPEC.loader.exec_module(lead_cli)


class Milestone3AIDraftTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        lead_cli.initialize_db(self.connection)
        now = lead_cli.utc_now()
        self.connection.execute(
            """INSERT INTO leads
            (company,contact_name,job_title,phone,email,website,industry,country,employees,painpoint,status,created_at,updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?, 'QUALIFIED',?,?)""",
            ("Acme Digital", "Ada Example", "CEO", "+2348012345678", "ada@example.com", "https://acme.example", "Software", "Nigeria", "10", "Poor mobile UX is reducing conversions", now, now),
        )
        self.connection.commit()

    def tearDown(self):
        self.connection.close()

    def test_m3_draft_table_exists(self):
        tables = {r[0] for r in self.connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("outreach_drafts", tables)

    def test_successful_generation_is_persisted(self):
        fake = "Your mobile checkout experience may be costing you conversions. I can help improve the UX and automate lead follow-up. Would you be open to a quick look?"
        with patch.object(lead_cli, "call_ollama", return_value=fake):
            draft_id = lead_cli.generate_draft(self.connection, 1, {"ai_model": "qwen2.5:0.5b-instruct-q4_K_M"})
        row = self.connection.execute("SELECT * FROM outreach_drafts WHERE id=?", (draft_id,)).fetchone()
        self.assertEqual(row["status"], "GENERATED")
        self.assertEqual(row["message"], fake)
        self.assertEqual(row["model"], "qwen2.5:0.5b-instruct-q4_K_M")

    def test_generation_requires_qualified_lead(self):
        self.connection.execute("UPDATE leads SET status='NEW' WHERE id=1")
        self.connection.commit()
        with patch.object(lead_cli, "call_ollama") as mocked:
            with self.assertRaises(ValueError):
                lead_cli.generate_draft(self.connection, 1, {"ai_model": "qwen2.5:0.5b-instruct-q4_K_M"})
        mocked.assert_not_called()

    def test_three_sentence_limit(self):
        text = "One. Two. Three. Four."
        self.assertFalse(lead_cli.validate_draft(text)[0])

    def test_placeholders_are_rejected(self):
        valid, reason = lead_cli.validate_draft("Hello {company}, I can help improve your UX.")
        self.assertFalse(valid)
        self.assertIn("placeholder", reason.lower())

    def test_empty_ai_response_is_rejected(self):
        with patch.object(lead_cli, "call_ollama", return_value=""):
            with self.assertRaises(ValueError):
                lead_cli.generate_draft(self.connection, 1, {"ai_model": "qwen2.5:0.5b-instruct-q4_K_M"})
        count = self.connection.execute("SELECT COUNT(*) FROM outreach_drafts").fetchone()[0]
        self.assertEqual(count, 0)

    def test_ollama_failure_does_not_create_draft(self):
        with patch.object(lead_cli, "call_ollama", side_effect=RuntimeError("Ollama unavailable")):
            with self.assertRaises(RuntimeError):
                lead_cli.generate_draft(self.connection, 1, {"ai_model": "qwen2.5:0.5b-instruct-q4_K_M"})
        count = self.connection.execute("SELECT COUNT(*) FROM outreach_drafts").fetchone()[0]
        self.assertEqual(count, 0)

    def test_approve_changes_only_draft_status(self):
        fake = "A concise outreach message can address the lead's specific business problem. Would you be open to a quick look?"
        with patch.object(lead_cli, "call_ollama", return_value=fake):
            draft_id = lead_cli.generate_draft(self.connection, 1, {"ai_model": "qwen2.5:0.5b-instruct-q4_K_M"})
        lead_cli.review_draft(self.connection, draft_id, "APPROVED")
        row = self.connection.execute("SELECT status FROM outreach_drafts WHERE id=?", (draft_id,)).fetchone()
        self.assertEqual(row["status"], "APPROVED")

    def test_reject_changes_only_draft_status(self):
        fake = "A concise outreach message can address the lead's specific business problem. Would you be open to a quick look?"
        with patch.object(lead_cli, "call_ollama", return_value=fake):
            draft_id = lead_cli.generate_draft(self.connection, 1, {"ai_model": "qwen2.5:0.5b-instruct-q4_K_M"})
        lead_cli.review_draft(self.connection, draft_id, "REJECTED")
        row = self.connection.execute("SELECT status FROM outreach_drafts WHERE id=?", (draft_id,)).fetchone()
        self.assertEqual(row["status"], "REJECTED")

    def test_review_does_not_send(self):
        fake = "A concise outreach message can address the lead's specific business problem. Would you be open to a quick look?"
        with patch.object(lead_cli, "call_ollama", return_value=fake):
            draft_id = lead_cli.generate_draft(self.connection, 1, {"ai_model": "qwen2.5:0.5b-instruct-q4_K_M"})
        with patch.object(lead_cli, "send_whatsapp_message") as sender:
            lead_cli.review_draft(self.connection, draft_id, "APPROVED")
        sender.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
