import csv
import importlib.util
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("lead_cli", ROOT / "lead_cli.py")
lead_cli = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
# Register the dynamically loaded module before dataclass processes its classes.
sys.modules[SPEC.name] = lead_cli
SPEC.loader.exec_module(lead_cli)


class Milestone1Tests(unittest.TestCase):
    def setUp(self):
        self.connection = sqlite3.connect(":memory:")
        self.connection.row_factory = sqlite3.Row
        lead_cli.initialize_db(self.connection)

    def tearDown(self):
        self.connection.close()

    def test_database_tables_are_created(self):
        tables = {
            row[0]
            for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        self.assertTrue({"leads", "outreach", "daily_usage"}.issubset(tables))

    def test_phone_normalization(self):
        self.assertEqual(lead_cli.normalize_phone("+234 801-234 (5678)"), "+2348012345678")

    def test_valid_phone(self):
        self.assertTrue(lead_cli.valid_phone("+2348012345678"))

    def test_invalid_phone(self):
        self.assertFalse(lead_cli.valid_phone("123"))

    def test_valid_email(self):
        self.assertTrue(lead_cli.valid_email("ceo@example.com"))

    def test_invalid_email(self):
        self.assertFalse(lead_cli.valid_email("not-an-email"))

    def test_missing_contact_is_invalid(self):
        errors = lead_cli.validate_row({"Company": "No Contact Co", "Phone": "", "Email": ""})
        self.assertIn("no phone or email", errors)

    def test_valid_row_is_accepted(self):
        errors = lead_cli.validate_row(
            {"Company": "Example Co", "Phone": "+2348012345678", "Email": "ceo@example.com"}
        )
        self.assertEqual(errors, [])

    def test_csv_import(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Company", "Contact Name", "Phone", "Email"])
                writer.writerow(["Example Co", "Ada Example", "+2348012345678", "ada@example.com"])
                writer.writerow(["Second Co", "John Example", "+2348098765432", "john@example.com"])
            imported, duplicates, invalid = lead_cli.import_csv(str(path), self.connection)
            self.assertEqual((imported, duplicates, invalid), (2, 0, 0))
            self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0], 2)

    def test_duplicate_import_is_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "leads.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Company", "Phone", "Email"])
                writer.writerow(["Example Co", "+2348012345678", "ada@example.com"])
            self.assertEqual(lead_cli.import_csv(str(path), self.connection), (1, 0, 0))
            self.assertEqual(lead_cli.import_csv(str(path), self.connection), (0, 1, 0))

    def test_invalid_rows_are_not_inserted(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid.csv"
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Company", "Phone", "Email"])
                writer.writerow(["Bad Phone", "123", "ceo@example.com"])
                writer.writerow(["Bad Email", "+2348012345678", "invalid"])
                writer.writerow(["No Contact", "", ""])
            self.assertEqual(lead_cli.import_csv(str(path), self.connection), (0, 0, 3))
            self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM leads").fetchone()[0], 0)

    def test_score_lead_is_bounded_and_explainable(self):
        lead = lead_cli.Lead(
            company="Example Co",
            job_title="CEO",
            phone="+2348012345678",
            email="ceo@example.com",
            website="https://example.com",
            industry="Software",
            employees="10",
            painpoint="Poor mobile UX",
        )
        score, reasons = lead_cli.score_lead(lead)
        self.assertGreaterEqual(score, 0)
        self.assertLessEqual(score, 100)
        self.assertIn("phone available", reasons)
        self.assertIn("painpoint supplied", reasons)

    def test_daily_stats_handle_no_usage_row(self):
        # Regression test for the bug found during manual M1 verification.
        row = self.connection.execute(
            "SELECT messages_sent FROM daily_usage WHERE usage_date=?", ("2099-01-01",)
        ).fetchone()
        self.assertIsNone(row)
        # The absence of a row is valid; stats must interpret it as zero.
        today = lead_cli.datetime.now(lead_cli.timezone.utc).date().isoformat()
        usage_row = self.connection.execute(
            "SELECT messages_sent FROM daily_usage WHERE usage_date=?", (today,)
        ).fetchone()
        self.assertIsNone(usage_row)


if __name__ == "__main__":
    unittest.main(verbosity=2)
