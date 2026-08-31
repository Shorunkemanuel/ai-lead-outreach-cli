import unittest

from messaging import (
    DeliveryResult,
    MessagingProvider,
    MockEmailProvider,
    MockWhatsAppProvider,
    MessagingRegistry,
    default_registry,
)


class Milestone6MessagingTests(unittest.TestCase):

    def test_email_provider_exists(self):
        provider = MockEmailProvider()

        self.assertEqual(provider.channel, "email")
        self.assertEqual(provider.name, "mock_email")

    def test_whatsapp_provider_exists(self):
        provider = MockWhatsAppProvider()

        self.assertEqual(provider.channel, "whatsapp")
        self.assertEqual(provider.name, "mock_whatsapp")

    def test_email_mock_delivery(self):
        provider = MockEmailProvider()

        result = provider.send(
            "test@example.com",
            "Test message",
        )

        self.assertIsInstance(result, DeliveryResult)
        self.assertTrue(result.success)
        self.assertEqual(result.channel, "email")
        self.assertEqual(result.provider, "mock_email")

    def test_whatsapp_mock_delivery(self):
        provider = MockWhatsAppProvider()

        result = provider.send(
            "+2348012345678",
            "Test message",
        )

        self.assertIsInstance(result, DeliveryResult)
        self.assertTrue(result.success)
        self.assertEqual(result.channel, "whatsapp")
        self.assertEqual(result.provider, "mock_whatsapp")

    def test_registry_selects_email_provider(self):
        registry = default_registry()

        provider = registry.get("email", "mock_email")

        self.assertIsInstance(provider, MockEmailProvider)

    def test_registry_selects_whatsapp_provider(self):
        registry = default_registry()

        provider = registry.get("whatsapp", "mock_whatsapp")

        self.assertIsInstance(provider, MockWhatsAppProvider)

    def test_registry_rejects_unknown_provider(self):
        registry = default_registry()

        with self.assertRaises(ValueError):
            registry.get("email", "unknown_provider")

    def test_registry_lists_email_providers(self):
        registry = default_registry()

        self.assertEqual(
            registry.providers_for_channel("email"),
            ["mock_email"],
        )

    def test_registry_lists_whatsapp_providers(self):
        registry = default_registry()

        self.assertEqual(
            registry.providers_for_channel("whatsapp"),
            ["mock_whatsapp"],
        )


if __name__ == "__main__":
    unittest.main()


class Milestone6QueueIntegrationTests(unittest.TestCase):

    def setUp(self):
        import sqlite3
        import lead_cli
        import m4_outreach

        self.sqlite3 = sqlite3
        self.lead_cli = lead_cli
        self.m4_outreach = m4_outreach

        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row

        lead_cli.initialize_db(self.connection)
        m4_outreach.initialize_m4(self.connection)

        self.connection.execute("""
            INSERT INTO leads (
                company, contact_name, job_title, email, phone,
                status, created_at, updated_at
            )
            VALUES (
                'M6 Test Company', 'Jane Doe', 'Founder',
                'jane@example.com', '+2348012345678',
                'QUALIFIED', '2026-08-31T00:00:00+00:00',
                '2026-08-31T00:00:00+00:00'
            )
        """)

        self.connection.execute("""
            INSERT INTO outreach_drafts (
                lead_id, status, message, model, prompt,
                validation_error, created_at
            )
            VALUES (
                1, 'APPROVED',
                'A short approved test message.',
                'test-model',
                'test prompt',
                '',
                '2026-08-31T00:00:00+00:00'
            )
        """)

        self.connection.commit()

    def test_queue_can_record_email_channel(self):
        draft_id = 1

        result = self.m4_outreach.queue_draft(
            self.connection,
            draft_id,
            channel="email",
            provider="mock_email",
        )

        self.assertTrue(result.queued)

        row = self.connection.execute(
            """
            SELECT channel, provider, destination, status
            FROM outreach_queue
            WHERE draft_id=?
            """,
            (draft_id,),
        ).fetchone()

        self.assertEqual(row["channel"], "email")
        self.assertEqual(row["provider"], "mock_email")
        self.assertEqual(row["destination"], "jane@example.com")
        self.assertEqual(row["status"], "QUEUED")

    def test_queue_can_record_whatsapp_channel(self):
        draft_id = 1

        result = self.m4_outreach.queue_draft(
            self.connection,
            draft_id,
            channel="whatsapp",
            provider="mock_whatsapp",
        )

        self.assertTrue(result.queued)

        row = self.connection.execute(
            """
            SELECT channel, provider, destination, status
            FROM outreach_queue
            WHERE draft_id=?
            """,
            (draft_id,),
        ).fetchone()

        self.assertEqual(row["channel"], "whatsapp")
        self.assertEqual(row["provider"], "mock_whatsapp")
        self.assertEqual(row["destination"], "+2348012345678")
        self.assertEqual(row["status"], "QUEUED")

    def test_queue_rejects_unsupported_provider(self):
        with self.assertRaises(ValueError):
            self.m4_outreach.queue_draft(
                self.connection,
                1,
                channel="email",
                provider="unknown_provider",
            )


if __name__ == "__main__":
    unittest.main()
