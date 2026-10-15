import unittest
from datetime import datetime,timezone
from audit_uploaded_clock_bridge import parse_utc,seconds,json_obj

class ClockTests(unittest.TestCase):
 def test_timezone_equivalent(self):
  self.assertEqual(seconds('2026-06-01T12:00:00Z','2026-06-01T14:00:00+02:00'),0)
 def test_delay_sign(self):
  self.assertEqual(seconds('2026-06-01T14:01:00Z','2026-06-01T12:00:00Z'),7260)
 def test_naive_rejected(self):
  self.assertIsNone(parse_utc('2026-06-01 12:00:00'))
  self.assertIsNone(seconds('2026-06-01 12:00:00','2026-06-01T12:00:00Z'))
 def test_bad_json_not_attested(self):
  self.assertEqual(json_obj('not-json'),{})
  self.assertEqual(json_obj('[1,2]'),{})
 def test_unverified_score_never_used_to_infer_time(self):
  self.assertIsNone(seconds('None','2026-06-01T12:00:00Z'))
if __name__=='__main__':unittest.main()