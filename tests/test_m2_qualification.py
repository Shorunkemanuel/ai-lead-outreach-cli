import importlib.util
import io
import json
import sqlite3
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lead_cli_m2", ROOT / "lead_cli.py")
lead_cli = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = lead_cli
assert SPEC.loader is not None
SPEC.loader.exec_module(lead_cli)


class Milestone2QualificationTests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        lead_cli.initialize_db(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_m2_columns_and_indexes_exist(self):
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(leads)")}
        self.assertTrue({"qualification_score", "qualification_priority", "qualification_reasons", "qualification_gaps", "qualified_at"}.issubset(columns))
        indexes = {row[1] for row in self.connection.execute("PRAGMA index_list(leads)")}
        self.assertIn("idx_leads_priority", indexes)
        self.assertIn("idx_leads_score", indexes)

    def test_high_qualification(self):
        lead = lead_cli.Lead(company="High Fit Co", contact_name="Ada", job_title="CEO", phone="+2348012345678", email="ada@example.com", website="https://example.com", industry="Software", country="Nigeria", employees="10", painpoint="Poor mobile UX causes checkout abandonment", source="Apollo")
        result = lead_cli.qualify_lead(lead)
        self.assertGreaterEqual(result.score, 80)
        self.assertEqual(result.priority, "HIGH")

    def test_medium_qualification(self):
        lead = lead_cli.Lead(company="Medium Fit Co", job_title="Manager", phone="+2348012345678", website="https://example.com", industry="Software", employees="10", painpoint="Poor mobile UX")
        result = lead_cli.qualify_lead(lead)
        self.assertGreaterEqual(result.score, 60)
        self.assertLess(result.score, 80)
        self.assertEqual(result.priority, "MEDIUM")

    def test_low_qualification(self):
        lead = lead_cli.Lead(company="Low Fit Co", phone="+2348012345678", industry="Software", employees="10", painpoint="Poor mobile UX")
        result = lead_cli.qualify_lead(lead)
        self.assertGreaterEqual(result.score, 40)
        self.assertLess(result.score, 60)
        self.assertEqual(result.priority, "LOW")

    def test_skip_qualification(self):
        result = lead_cli.qualify_lead(lead_cli.Lead(company="Incomplete Co"))
        self.assertLess(result.score, 40)
        self.assertEqual(result.priority, "SKIP")
        self.assertTrue(result.gaps)

    def test_score_is_always_bounded(self):
        leads = [lead_cli.Lead(company="Empty"), lead_cli.Lead(company="Full", contact_name="Ada", job_title="CEO", phone="+2348012345678", email="ada@example.com", website="https://example.com", industry="Software", country="Nigeria", employees="10", painpoint="Poor mobile UX causes checkout abandonment", source="Apollo")]
        for lead in leads:
            result = lead_cli.qualify_lead(lead)
            self.assertGreaterEqual(result.score, 0)
            self.assertLessEqual(result.score, 100)

    def test_reasons_and_gaps_are_explainable(self):
        lead = lead_cli.Lead(company="Explainable Co", job_title="CEO", phone="+2348012345678", painpoint="Manual lead scoring takes hours")
        result = lead_cli.qualify_lead(lead)
        self.assertIn("decision maker identified", result.reasons)
        self.assertIn("phone available", result.reasons)
        self.assertIn("email available", result.gaps if result.gaps else ())
        self.assertIn("website unknown", result.gaps)

    def test_qualification_is_persisted_to_sqlite(self):
        now = lead_cli.utc_now()
        self.connection.execute("""INSERT INTO leads (company,contact_name,job_title,phone,email,website,industry,country,employees,painpoint,source,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,'NEW',?,?)""", ("Persist Co", "Ada", "CEO", "+2348012345678", "ada@example.com", "https://example.com", "Software", "Nigeria", "10", "Poor mobile UX", "test", now, now))
        self.connection.commit()
        self.assertEqual(lead_cli.qualify_all(self.connection, lead_cli.load_config("/nonexistent/config.json")), 1)
        row = self.connection.execute("SELECT qualification_score,qualification_priority,qualification_reasons,qualification_gaps,qualified_at,status FROM leads").fetchone()
        self.assertIsNotNone(row["qualification_score"])
        self.assertIn(row["qualification_priority"], {"HIGH", "MEDIUM", "LOW", "SKIP"})
        self.assertTrue(json.loads(row["qualification_reasons"]))
        self.assertIsNotNone(row["qualified_at"])
        self.assertEqual(row["status"], "QUALIFIED")

    def test_qualification_is_deterministic(self):
        lead = lead_cli.Lead(company="Stable Co", job_title="CEO", phone="+2348012345678", email="ceo@example.com", website="https://example.com", industry="Software", employees="10", painpoint="Poor mobile UX")
        self.assertEqual(lead_cli.qualify_lead(lead), lead_cli.qualify_lead(lead))

    def test_priority_filter_outputs_only_requested_priority(self):
        now = lead_cli.utc_now()
        self.connection.executemany("""INSERT INTO leads (company,job_title,phone,email,website,industry,employees,painpoint,status,created_at,updated_at) VALUES (?,?,?,?,?,?,?,?,'NEW',?,?)""", [("High Co", "CEO", "+2348012345678", "ceo@high.com", "https://high.com", "Software", "10", "Poor mobile UX causes checkout abandonment", now, now), ("Skip Co", "", "+2348012345679", "", "", "", "", "", now, now)])
        self.connection.commit()
        lead_cli.qualify_all(self.connection, lead_cli.load_config("/nonexistent/config.json"))
        output = io.StringIO()
        with redirect_stdout(output): lead_cli.show_qualified(self.connection, "high")
        text = output.getvalue()
        self.assertIn("High Co", text)
        self.assertNotIn("Skip Co", text)

    def test_existing_m1_lead_survives_qualification(self):
        now = lead_cli.utc_now()
        self.connection.execute("INSERT INTO leads(company,phone,email,status,created_at,updated_at) VALUES(?,?,?,?,?,?)", ("M1 Existing Co", "+2348012345678", "old@example.com", "NEW", now, now))
        self.connection.commit()
        before = self.connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        lead_cli.qualify_all(self.connection, lead_cli.load_config("/nonexistent/config.json"))
        after = self.connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0]
        self.assertEqual(before, after)
        self.assertEqual(self.connection.execute("SELECT company FROM leads").fetchone()[0], "M1 Existing Co")


if __name__ == "__main__": unittest.main(verbosity=2)
