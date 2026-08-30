import sqlite3
import unittest

import lead_cli
import m4_outreach


class Milestone5HumanReviewTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        lead_cli.initialize_db(self.connection)
        m4_outreach.initialize_m4(self.connection)

        self.connection.execute(
            """INSERT INTO leads (
                company, contact_name, job_title, phone, email,
                website, industry, country, employees, painpoint,
                source, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "Test Company", "Jane Doe", "Founder", "+2348012345678",
                "jane@example.com", "https://example.com", "Software", "Nigeria",
                "10", "Manual lead follow-up is slow", "test", "QUALIFIED",
                "2026-08-30T00:00:00+00:00", "2026-08-30T00:00:00+00:00",
            ),
        )

        message = (
            "Your manual lead follow-up is slowing the sales process. "
            "I can help streamline that workflow with practical automation; "
            "would you be open to a short conversation?"
        )
        self.connection.execute(
            """INSERT INTO outreach_drafts (
                lead_id, status, message, model, prompt,
                validation_error, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (1, "GENERATED", message, "test-model", "test prompt", "", "2026-08-30T00:00:00+00:00"),
        )
        self.connection.commit()

    def test_generated_draft_can_be_approved(self):
        m4_outreach.approve_draft(self.connection, 1)
        row = self.connection.execute("SELECT status, reviewed_at FROM outreach_drafts WHERE id=1").fetchone()
        self.assertEqual(row["status"], "APPROVED")
        self.assertIsNotNone(row["reviewed_at"])

    def test_approval_does_not_send(self):
        m4_outreach.approve_draft(self.connection, 1)
        self.assertIsNone(self.connection.execute("SELECT status FROM outreach WHERE lead_id=1").fetchone())

    def test_approval_is_audited(self):
        m4_outreach.approve_draft(self.connection, 1)
        row = self.connection.execute("SELECT event, detail FROM outreach_events WHERE draft_id=1 ORDER BY id DESC LIMIT 1").fetchone()
        self.assertEqual(row["event"], "APPROVED")
        self.assertIn("human approval", row["detail"])

    def test_rejected_draft_is_not_approved(self):
        lead_cli.review_draft(self.connection, 1, "REJECTED")
        row = self.connection.execute("SELECT status FROM outreach_drafts WHERE id=1").fetchone()
        self.assertEqual(row["status"], "REJECTED")
        with self.assertRaises(ValueError):
            m4_outreach.approve_draft(self.connection, 1)

    def test_review_does_not_send(self):
        lead_cli.review_draft(self.connection, 1, "REJECTED")
        self.assertIsNone(self.connection.execute("SELECT status FROM outreach WHERE lead_id=1").fetchone())

    def test_message_remains_auditable_after_review(self):
        original = self.connection.execute("SELECT message FROM outreach_drafts WHERE id=1").fetchone()["message"]
        lead_cli.review_draft(self.connection, 1, "REJECTED")
        current = self.connection.execute("SELECT message FROM outreach_drafts WHERE id=1").fetchone()["message"]
        self.assertEqual(current, original)


if __name__ == "__main__":
    unittest.main()
