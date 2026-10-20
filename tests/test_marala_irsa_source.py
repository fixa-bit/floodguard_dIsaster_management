"""Prevent alternate reports from silently becoming fabricated 06:00 readings."""
import unittest
from scripts.audit_marala_irsa_source import parse_report


class IrsaReportTests(unittest.TestCase):
    html = '''<div data-reading-date="2025-01-15"><h3>MARALA</h3>
        <span>U/S DISCHARGE</span><strong>5,533 <small>Cs</small></strong>
        <span>D/S DISCHARGE</span><strong>5,533 <small>Cs</small></strong>
        <h3>PANJNAD</h3></div>'''

    def test_uses_requested_report_date_and_keeps_time_unknown(self):
        row = parse_report(self.html, "2025-01-15")
        self.assertEqual(row["inflow_cusecs"], 5533)
        self.assertIsNone(row["observed_at"])
        self.assertIn("unconfirmed", row["measurement_kind"])

    def test_wrong_date_response_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "date"):
            parse_report(self.html, "2026-01-15")

    def test_no_station_cannot_become_zero_flow(self):
        self.assertIsNone(parse_report(self.html.replace("MARALA", "MANGLA"), "2025-01-15"))

    def test_unknown_flow_cannot_become_zero(self):
        with self.assertRaises(ValueError):
            parse_report(self.html.replace("5,533", "N/A"), "2025-01-15")
