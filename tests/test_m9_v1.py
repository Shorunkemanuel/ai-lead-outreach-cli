import json
import sqlite3
import unittest

import lead_cli
import m4_outreach
import m8_stats


class Milestone9V1Tests(unittest.TestCase):
    """Final V1 acceptance and regression tests."""

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        lead_cli.init_db(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_v1_required_modules_import(self):
        import messaging  # noqa: F401

        self.assertTrue(hasattr(m4_outreach, "check_outreach_safety"))
        self.assertTrue(hasattr(m8_stats, "print_stats"))

    def test_database_contains_core_workflow_tables(self):
        rows = self.connection.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()

        tables = {row[0] for row in rows}

        self.assertIn("leads", tables)
        self.assertIn("outreach_drafts", tables)
        self.assertIn("outreach_queue", tables)

    def test_v1_lead_score_is_bounded(self):
        score = lead_cli.score_lead(
            {
                "name": "Test Lead",
                "email": "test@example.com",
                "phone": "+2348012345678",
                "company": "Example Ltd",
                "job_title": "CEO",
            }
        )

        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)

    def test_v1_safety_gate_is_present(self):
        decision = m4_outreach.check_outreach_safety(
            self.connection,
            lead_id=1,
            destination="test@example.com",
            channel="email",
            provider="mock_email",
        )

        self.assertTrue(hasattr(decision, "allowed"))
        self.assertTrue(hasattr(decision, "reason"))

    def test_v1_stats_report_is_json_serializable(self):
        report = m8_stats.build_stats(self.connection)

        encoded = json.dumps(report)
        decoded = json.loads(encoded)

        self.assertEqual(decoded, report)

    def test_v1_empty_database_report_is_deterministic(self):
        first = m8_stats.build_stats(self.connection)
        second = m8_stats.build_stats(self.connection)

        self.assertEqual(first, second)

    def test_v1_dry_run_contract_exists(self):
        self.assertTrue(hasattr(m4_outreach, "send_outreach"))

    def test_v1_no_secrets_in_test_environment(self):
        # The test suite must not require real provider credentials.
        self.assertIsNone(
            __import__("os").environ.get("OPENAI_API_KEY")
        )

    def test_v1_sqlite_connection_works(self):
        result = self.connection.execute(
            "SELECT 1"
        ).fetchone()

        self.assertEqual(result[0], 1)


if __name__ == "__main__":
    unittest.main()
