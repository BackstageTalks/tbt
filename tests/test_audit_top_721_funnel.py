"""Offline regression checks: no providers, model training, or database writes."""
import unittest
from audit_top_721_funnel import analyze_archive, analyze_snapshot


def row(*, p=0.72, priced=False, surface=8, depth=0.90,
        reasons=(), start="2026-11-16T14:00:00Z", section=None):
    return {
        "scheduled_at": start, "competition": "ATP",
        "blinq_probability": p, "data_depth": depth, "priced": priced,
        "samples": {"player1_surface_matches": surface,
                    "player2_surface_matches": surface},
        "top_rejection_reasons": list(reasons), "selected_section": section,
    }


def archive(*rows):
    return {"schema": 1, "snapshots": [
        {"generated_at": "2026-11-16T05:01:00Z", "rows": list(rows)},
        {"generated_at": "2026-11-16T07:00:00Z", "rows": list(rows)},
    ]}


class TestReadonlyFunnel(unittest.TestCase):
    def test_unpriced_is_not_counted_as_issued_or_top_qualified(self):
        data = archive(row(), row(priced=True, reasons=("insufficient_evidence",)),
                       row(priced=True, reasons=(), section="top_daily"))
        result = analyze_archive(data, "2026-11-16")["first_snapshot"]
        at65 = result["confidence_floor_funnel"]["65"]
        self.assertEqual(at65["model_probability_at_least"], 3)
        self.assertEqual(at65["unpriced_after_depth_and_surface"], 1)
        self.assertEqual(at65["passes_recorded_top_gates"], 1)
        self.assertEqual(result["selected_sections"]["top_daily"], 1)
        self.assertEqual(result["top_rejection_reasons_nonexclusive"]["insufficient_evidence"], 1)

    def test_timezone_boundary_and_wrong_day_rejected(self):
        result = analyze_snapshot({"rows": [
            row(), row(start="2026-11-17T12:00:00Z"),
            row(start="2026-11-16T03:30:00Z"),
            row(start="invalid"), row(start="2026-11-16T05:30:00Z"),
        ]}, "2026-11-16")
        self.assertEqual(result["today_singles"], 2)

    def test_poor_evidence_is_not_eligible_even_when_confident(self):
        result = analyze_snapshot({"rows": [
            row(p=.82, surface=1), row(p=.82, depth=.2, priced=True),
            row(p=.649, priced=True),
        ]}, "2026-11-16")
        self.assertEqual(result["confidence_floor_funnel"]["65"]["also_top_depth_and_surface"], 0)
        self.assertEqual(result["selected_sections"]["unselected"], 3)

    def test_no_valid_publication_time_fails_closed(self):
        with self.assertRaises(ValueError):
            analyze_archive({"snapshots": [
                {"generated_at": "2026-11-16T04:59:00Z", "rows": [row()]},
            ]}, "2026-11-16")

    def test_earliest_and_latest_snapshots_stay_separate(self):
        data = archive(row())
        data["snapshots"][1]["rows"].append(row())
        report = analyze_archive(data, "2026-11-16")
        self.assertEqual(report["first_snapshot"]["today_singles"], 1)
        self.assertEqual(report["last_snapshot"]["today_singles"], 2)


    def test_raw_to_adjusted_depth_loss_is_measured_without_changing_filters(self):
        strong = row(p=.72, priced=False, depth=.55)
        strong["raw_model_probability"] = .90
        strong["blinq_probability"] = .72
        secure = row(p=.81, priced=False, depth=.90)
        secure["raw_model_probability"] = .8444444444
        result = analyze_snapshot({"generated_at": "2026-11-16T05:02:00Z",
                                   "rows": [strong, secure]}, "2026-11-16")
        attr = result["confidence_attrition"]
        self.assertEqual(attr["thresholds"]["75"]["raw_at_least"], 2)
        self.assertEqual(attr["thresholds"]["75"]["lost_in_depth_adjustment"], 1)
        self.assertEqual(attr["thresholds"]["75"]["adjusted_at_least"], 1)
        self.assertEqual(attr["thresholds"]["75"]["passes_price_150"], 0)
        self.assertEqual(result["selected_sections"]["unselected"], 2)

    def test_strict_price_gate_requires_prestart_two_way_selected_side(self):
        from audit_top_721_funnel import quote_evidence
        def quoted():
            r = row(p=.75, priced=True)
            r.update({
                "player1": {"id": "a"}, "player2": {"id": "b"},
                "betting": {"selection_id": "a", "odds": 1.68,
                            "captured_at": "2026-11-16T04:58:00Z"},
                "two_way_market": {"player1_odds": 1.68, "player2_odds": 2.23,
                                   "captured_at": "2026-11-16T04:58:00Z"},
            })
            return r
        at = __import__("datetime").datetime.fromisoformat("2026-11-16T05:02:00+00:00")
        valid = quoted()
        self.assertEqual(quote_evidence(valid, at),
                         "verified_prestart_selected_price_ge_150")
        opposite = quoted()
        opposite["betting"]["odds"] = 2.23
        self.assertEqual(quote_evidence(opposite, at), "not_verified_two_way_quote")
        late = quoted()
        late["betting"]["captured_at"] = "2026-11-16T05:03:00Z"
        self.assertEqual(quote_evidence(late, at), "missing_or_late_quote_clock")
        too_short = quoted()
        too_short["betting"]["odds"] = 1.40
        self.assertEqual(quote_evidence(too_short, at), "selected_price_below_150")

    def test_inconsistent_depth_formula_never_counts_as_trusted_confidence(self):
        r = row(p=.95, priced=True, depth=.20)
        r["raw_model_probability"] = .95
        result = analyze_snapshot({"generated_at": "2026-11-16T05:02:00Z",
                                   "rows": [r]}, "2026-11-16")
        attr = result["confidence_attrition"]
        self.assertEqual(attr["probability_evidence_anomalies"]["inconsistent_depth_adjustment"], 1)
        self.assertEqual(attr["thresholds"]["80"]["adjusted_at_least"], 0)


if __name__ == "__main__":
    unittest.main()
