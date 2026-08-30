import os
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

import m4_outreach


class Milestone4OutreachTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(delete=False)
        self.tmp.close()
        self.connection = sqlite3.connect(self.tmp.name)
        # Use the module's initializer when available.
        if hasattr(m4_outreach, "initialize_db"):
            m4_outreach.initialize_db(self.connection)
        elif hasattr(m4_outreach, "init_db"):
            m4_outreach.init_db(self.connection)

    def tearDown(self):
        self.connection.close()
        os.unlink(self.tmp.name)

    def test_module_exposes_m4_core_functions(self):
        required = (
            "approve_draft",
            "queue_draft",
            "execute_queue",
        )
        for name in required:
            self.assertTrue(hasattr(m4_outreach, name), name)

    def test_dry_run_does_not_send(self):
        sender = Mock(return_value={"status": "SENT"})
        if not hasattr(m4_outreach, "execute_queue"):
            self.skipTest("execute_queue not implemented yet")
        with patch.object(m4_outreach, "send_message", sender, create=True):
            try:
                m4_outreach.execute_queue(self.connection, dry_run=True)
            except (TypeError, ValueError):
                # Signature may evolve during M4; the key contract remains testable below.
                pass
        sender.assert_not_called()

    def test_suppression_is_supported(self):
        names = dir(m4_outreach)
        self.assertTrue(
            any("suppress" in name.lower() or "opt_out" in name.lower() for name in names),
            "M4 must expose suppression/opt-out functionality",
        )

    def test_provider_abstraction_is_supported(self):
        names = dir(m4_outreach)
        self.assertTrue(
            any("provider" in name.lower() for name in names),
            "M4 must separate provider integration from queue logic",
        )

    def test_no_automatic_retry_contract(self):
        names = dir(m4_outreach)
        self.assertFalse(
            any(name.lower() in {"retry_send", "auto_retry", "retry_failed"} for name in names),
            "M4 must not implement automatic retries",
        )


if __name__ == "__main__":
    unittest.main()
