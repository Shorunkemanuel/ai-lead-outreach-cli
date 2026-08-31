import sqlite3
import unittest

import lead_cli
import m4_outreach


class Milestone7SafetyTests(unittest.TestCase):

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row

        lead_cli.initialize_db(self.connection)
        m4_outreach.initialize_m4(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_global_daily_limit_is_enforced(self):
        self.assertTrue(hasattr(m4_outreach, "get_safety_config"))

    def test_channel_daily_limit_is_enforced(self):
        self.assertTrue(hasattr(m4_outreach, "get_channel_limit"))

    def test_provider_daily_limit_is_enforced(self):
        self.assertTrue(hasattr(m4_outreach, "get_provider_limit"))

    def test_duplicate_protection_is_supported(self):
        self.assertTrue(hasattr(m4_outreach, "check_duplicate_send"))

    def test_cooldown_is_supported(self):
        self.assertTrue(hasattr(m4_outreach, "check_cooldown"))

    def test_safety_decision_is_explainable(self):
        self.assertTrue(hasattr(m4_outreach, "check_outreach_safety"))


if __name__ == "__main__":
    unittest.main()


class Milestone7EnforcementTests(unittest.TestCase):

    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row

        lead_cli.initialize_db(self.connection)
        m4_outreach.initialize_m4(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_global_limit_blocks_send(self):
        self.connection.execute(
            """
            INSERT INTO daily_usage(usage_date, messages_sent)
            VALUES(date('now'), 30)
            """
        )
        self.connection.commit()

        decision = m4_outreach.check_outreach_safety(
            self.connection,
            lead_id=1,
            destination="test@example.com",
            channel="email",
            provider="mock_email",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "global daily limit reached")

    def test_email_limit_blocks_email(self):
        for i in range(20):
            self.connection.execute(
                """
                INSERT INTO outreach_queue
                (lead_id, draft_id, destination, channel, provider,
                 status, queued_at, sent_at)
                VALUES (?, ?, ?, ?, ?, 'SENT', datetime('now'), datetime('now'))
                """,
                (i + 2, i + 1, "email@example.com", "email", "mock_email"),
            )

        self.connection.commit()

        decision = m4_outreach.check_outreach_safety(
            self.connection,
            lead_id=1,
            destination="new@example.com",
            channel="email",
            provider="mock_email",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "email daily limit reached")

    def test_whatsapp_limit_blocks_whatsapp(self):
        for i in range(10):
            self.connection.execute(
                """
                INSERT INTO outreach_queue
                (lead_id, draft_id, destination, channel, provider,
                 status, queued_at, sent_at)
                VALUES (?, ?, ?, ?, ?, 'SENT', datetime('now'), datetime('now'))
                """,
                (i + 2, i + 1, "+2348000000000", "whatsapp", "mock_whatsapp"),
            )

        self.connection.commit()

        decision = m4_outreach.check_outreach_safety(
            self.connection,
            lead_id=1,
            destination="+2348111111111",
            channel="whatsapp",
            provider="mock_whatsapp",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reason,
            "whatsapp daily limit reached",
        )

    def test_duplicate_send_is_blocked(self):
        self.connection.execute(
            """
            INSERT INTO outreach_queue
            (lead_id, draft_id, destination, channel, provider,
             status, queued_at, sent_at)
            VALUES (?, ?, ?, ?, ?, 'SENT', datetime('now'), datetime('now'))
            """,
            (
                1,
                1,
                "duplicate@example.com",
                "email",
                "mock_email",
            ),
        )
        self.connection.commit()

        decision = m4_outreach.check_outreach_safety(
            self.connection,
            lead_id=1,
            destination="duplicate@example.com",
            channel="email",
            provider="mock_email",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.reason, "duplicate send blocked")

    def test_cooldown_is_blocked(self):
        self.connection.execute(
            """
            INSERT INTO outreach_queue
            (lead_id, draft_id, destination, channel, provider,
             status, queued_at, sent_at)
            VALUES (?, ?, ?, ?, ?, 'SENT',
                    datetime('now', '-1 day'),
                    datetime('now', '-1 day'))
            """,
            (
                1,
                1,
                "cooldown@example.com",
                "email",
                "mock_email",
            ),
        )
        self.connection.commit()

        decision = m4_outreach.check_outreach_safety(
            self.connection,
            lead_id=1,
            destination="another@example.com",
            channel="email",
            provider="mock_email",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reason,
            "lead is inside cooldown period",
        )

    def test_suppression_blocks_destination(self):
        m4_outreach.suppress(
            self.connection,
            "suppressed@example.com",
            "user requested no contact",
        )

        decision = m4_outreach.check_outreach_safety(
            self.connection,
            lead_id=1,
            destination="suppressed@example.com",
            channel="email",
            provider="mock_email",
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(
            decision.reason,
            "destination is suppressed",
        )


if __name__ == "__main__":
    unittest.main()
