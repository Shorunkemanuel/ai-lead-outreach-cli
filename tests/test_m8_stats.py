import io
import json
import sqlite3
import unittest
from contextlib import redirect_stdout

import lead_cli
import m4_outreach
import m8_stats


class Milestone8StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        lead_cli.initialize_db(self.connection)
        m4_outreach.initialize_m4(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_empty_database_report_is_deterministic(self):
        stats = m8_stats.collect_stats(self.connection, daily_limit=30)
        self.assertEqual(stats["leads"]["total"], 0)
        self.assertEqual(stats["leads"]["by_status"], {})
        self.assertEqual(stats["leads"]["qualification"]["average_score"], None)
        self.assertEqual(stats["outreach"]["sent_today"], 0)
        self.assertEqual(stats["outreach"]["remaining_today"], 30)

    def test_lead_and_qualification_counts(self):
        now = lead_cli.utc_now()
        self.connection.execute(
            """
            INSERT INTO leads
            (company, contact_name, status, qualification_score,
             qualification_priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Alpha", "Ada", "QUALIFIED", 80, "HIGH", now, now),
        )
        self.connection.execute(
            """
            INSERT INTO leads
            (company, contact_name, status, qualification_score,
             qualification_priority, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("Beta", "Ben", "NEW", 60, "MEDIUM", now, now),
        )
        self.connection.commit()

        stats = m8_stats.collect_stats(self.connection)
        self.assertEqual(stats["leads"]["total"], 2)
        self.assertEqual(stats["leads"]["by_status"], {"NEW": 1, "QUALIFIED": 1})
        self.assertEqual(stats["leads"]["qualification"]["scored"], 2)
        self.assertEqual(stats["leads"]["qualification"]["average_score"], 70.0)
        self.assertEqual(stats["leads"]["qualification"]["by_priority"], {"HIGH": 1, "MEDIUM": 1})

    def test_outreach_statistics_are_channel_and_provider_aware(self):
        now = lead_cli.utc_now()
        for lead_id, draft_id, channel, provider in (
            (1, 1, "email", "mock_email"),
            (2, 2, "email", "mock_email"),
            (3, 3, "whatsapp", "mock_whatsapp"),
        ):
            self.connection.execute(
                """
                INSERT INTO outreach_queue
                (lead_id, draft_id, destination, channel, provider,
                 status, queued_at, sent_at)
                VALUES (?, ?, ?, ?, ?, 'SENT', ?, ?)
                """,
                (lead_id, draft_id, f"dest-{lead_id}", channel, provider, now, now),
            )
        today = now[:10]
        self.connection.execute(
            "INSERT INTO daily_usage(usage_date, messages_sent) VALUES(?, ?)",
            (today, 3),
        )
        self.connection.commit()

        stats = m8_stats.collect_stats(self.connection, daily_limit=10)
        self.assertEqual(stats["outreach"]["sent_today"], 3)
        self.assertEqual(stats["outreach"]["remaining_today"], 7)
        self.assertEqual(stats["outreach"]["queue_sent_today"], 3)
        self.assertEqual(stats["outreach"]["sent_today_by_channel"], {"email": 2, "whatsapp": 1})
        self.assertEqual(stats["outreach"]["sent_today_by_provider"], {"mock_email": 2, "mock_whatsapp": 1})

    def test_print_stats_does_not_mutate_database(self):
        before = self.connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        output = io.StringIO()
        with redirect_stdout(output):
            m8_stats.print_stats(m8_stats.collect_stats(self.connection))
        after = self.connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        self.assertEqual(before, after)
        self.assertIn("Leads", output.getvalue())
        self.assertIn("Outreach", output.getvalue())

    def test_json_output_is_valid(self):
        output = io.StringIO()
        stats = m8_stats.collect_stats(self.connection)
        with redirect_stdout(output):
            print(json.dumps(stats, sort_keys=True))
        decoded = json.loads(output.getvalue())
        self.assertEqual(decoded["version"], "M8")

    def test_cli_parser_exposes_polished_reporting_options(self):
        parser = m8_stats.build_parser()
        args = parser.parse_args(["--db", "custom.db", "--limit", "25", "--section", "outreach", "--json"])
        self.assertEqual(args.db, "custom.db")
        self.assertEqual(args.limit, 25)
        self.assertEqual(args.section, "outreach")
        self.assertTrue(args.as_json)


if __name__ == "__main__":
    unittest.main()
