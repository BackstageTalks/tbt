from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tbt.models.evidence_selection_audit import audit_preissued_reliability, issued_cohort_digest


START = datetime(2026, 10, 20, 10, tzinfo=timezone.utc)
MODEL_SHA = "a" * 64
SOURCE_SHA = "b" * 64
WINDOWS = [
    ("development", START - timedelta(days=5), START + timedelta(days=1)),
    ("untouched", START + timedelta(days=1), START + timedelta(days=10)),
]
METRICS = ("serve", "return", "second_serve", "bp_save", "bp_convert")


def evidence(player, *, thin=False):
    depth = 3 if thin else 20
    return {
        "tour": "atp", "canonical_player_id": player,
        "matches_recent": depth, "matches_surface": 1 if thin else 12,
        "covered_matches": {name: depth for name in METRICS},
        "stat_opportunities": {name: 400 for name in METRICS},
    }


def row(key, *, at=START, settled=True, right_thin=False, correct=True,
        level="main", side="left"):
    return {
        "match_id": key, "tour": "ATP", "competition_level": level,
        "issued_at": at, "scheduled_at": at + timedelta(hours=3),
        "evidence_as_of": at, "evidence_provenance_verified": True,
        "left": evidence("A"), "right": evidence("B", thin=right_thin),
        "model_probabilities": {
            "elo": {"left_player_id": "A", "probability": .80},
            "hgb": {"left_player_id": "A", "probability": .82},
        },
        "candidate_probability_left": .80, "selected_side": side,
        "candidate_model_sha256": MODEL_SHA,
        "status": "settled" if settled else "pending",
        "target_left_won": (correct if side == "left" else not correct)
        if settled else None,
        "settled_at": at + timedelta(days=1) if settled else None,
    }


def run(rows, windows=WINDOWS):
    return audit_preissued_reliability(
        rows, fixed_model_sha256=MODEL_SHA,
        frozen_cohort_sha256=issued_cohort_digest(rows), windows=windows,
    )


def test_abstention_is_scored_on_all_issued_rows_before_outcomes():
    rows = [
        row("r1", correct=True),
        row("r2", right_thin=True, correct=False, level="challenger"),
        row("r3", right_thin=True, settled=False, level="itf"),
        row("r4", at=START + timedelta(days=2), correct=False),
    ]
    original = deepcopy(rows)
    report = run(rows)
    assert rows == original
    dev = report["windows"]["development"]
    assert dev["all_issued"]["issued"] == 3
    assert dev["all_issued"]["settled"] == 2
    assert dev["retained"]["issued"] == 1
    assert dev["retained"]["wins"] == 1
    assert dev["withheld"]["issued"] == 2
    assert dev["withheld"]["settled"] == 1
    assert dev["withheld"]["losses"] == 1
    assert dev["by_competition"]["challenger"]["withheld"]["issued"] == 1
    assert dev["by_competition"]["itf"]["withheld"]["pending_or_void"] == 1
    assert dev["by_confidence"]["80_plus"]["all_issued"]["issued"] == 3
    assert report["windows"]["untouched"]["retained"]["wins"] == 0
    assert report["model_fitted"] is False
    assert report["production_mutated"] is False
    assert "roi" not in str(report).lower()
    assert dev["statistical_improvement_verified"] is False


def test_same_preissued_filter_decision_independent_of_future_outcome():
    win = row("a", right_thin=True, correct=True)
    loss = row("a", right_thin=True, correct=False)
    assert run([win])["windows"]["development"]["withheld"]["issued"] == 1
    assert run([loss])["windows"]["development"]["withheld"]["issued"] == 1


def test_atp_wta_and_level_segmentation_never_assumes_other_tour():
    atp = row("a")
    wta = row("b", level="itf")
    wta.update(tour="WTA", left={**evidence("A"), "tour": "wta"},
               right={**evidence("B"), "tour": "wta"})
    report = run([atp, wta])["windows"]["development"]
    assert report["by_tour"]["atp"]["retained"]["issued"] == 1
    assert report["by_tour"]["wta"]["retained"]["issued"] == 1
    assert report["by_competition"]["itf"]["retained"]["settled"] == 1


@pytest.mark.parametrize("bad", [
    {"issued_at": START + timedelta(hours=3)},
    {"issued_at": START + timedelta(hours=2, minutes=50)},
    {"evidence_as_of": START + timedelta(seconds=1)},
    {"evidence_provenance_verified": False},
    {"issued_at": START.replace(tzinfo=None)},
    {"competition_level": ""},
    {"tour": "unknown"},
    {"candidate_probability_left": float("nan")},
    {"selected_side": "unknown"},
    {"status": "unknown"},
])
def test_bad_prestart_provenance_or_candidate_cohort_fails_closed(bad):
    item = row("x")
    item.update(bad)
    with pytest.raises(ValueError):
        run([item])


def test_pending_and_void_results_cannot_leak_into_selection_or_scoring():
    item = row("p", settled=False)
    item["target_left_won"] = True
    with pytest.raises(ValueError):
        run([item])
    item["target_left_won"] = None
    item["settled_at"] = START + timedelta(days=2)
    with pytest.raises(ValueError):
        run([item])
    item = row("x")
    item["settled_at"] = START - timedelta(days=1)
    with pytest.raises(ValueError):
        run([item])


def test_duplicate_rows_and_missing_or_overlapping_frozen_windows_are_rejected():
    one = row("x")
    with pytest.raises(ValueError, match="duplicate"):
        run([one, deepcopy(one)])
    with pytest.raises(ValueError, match="overlapping"):
        run([one], windows=[
            ("d", START - timedelta(days=1), START + timedelta(days=2)),
            ("f", START + timedelta(days=1), START + timedelta(days=3)),
        ])
    with pytest.raises(ValueError, match="exactly one"):
        run([one], windows=[("later", START + timedelta(days=1),
                             START + timedelta(days=2))])


def test_unknown_second_model_is_abstention_not_invented_agreement():
    item = row("x")
    item["model_probabilities"] = {
        "elo": {"left_player_id": "A", "probability": .80},
    }
    report = run([item])["windows"]["development"]
    assert report["retained"]["issued"] == 0
    assert report["withheld"]["issued"] == 1
    assert report["gate_reasons"]["missing_or_invalid_model_disagreement"] == 1


def test_preissued_cohort_digest_detects_modified_probability_or_missing_fixture():
    original = [row("a"), row("b", settled=False)]
    frozen_digest = issued_cohort_digest(original)
    updated = deepcopy(original)
    updated[0]["candidate_probability_left"] = .90
    with pytest.raises(ValueError, match="SHA256 read-back mismatch"):
        audit_preissued_reliability(
            updated, fixed_model_sha256=MODEL_SHA,
            frozen_cohort_sha256=frozen_digest, windows=WINDOWS,
        )
    with pytest.raises(ValueError, match="SHA256 read-back mismatch"):
        audit_preissued_reliability(
            original[:1], fixed_model_sha256=MODEL_SHA,
            frozen_cohort_sha256=frozen_digest, windows=WINDOWS,
        )
    # Results can arrive later without rewriting the earlier opportunity set.
    later = deepcopy(original)
    later[1].update(status="settled", target_left_won=False,
                    settled_at=START + timedelta(days=1))
    assert issued_cohort_digest(later) == frozen_digest


def test_each_issued_row_must_match_pinned_candidate_binary():
    item = row("x")
    item["candidate_model_sha256"] = "c" * 64
    with pytest.raises(ValueError, match="model digest differs"):
        run([item])


def test_pinned_hash_and_identity_protections():
    with pytest.raises(ValueError, match="Pinned"):
        audit_preissued_reliability(
            [row("x")], fixed_model_sha256="x", frozen_cohort_sha256=SOURCE_SHA,
            windows=WINDOWS,
        )
    item = row("x")
    item["right"]["canonical_player_id"] = "A"
    with pytest.raises(ValueError, match="Distinct"):
        run([item])


def test_wilson_interval_does_not_certify_80_percent_from_tiny_sample():
    report = run([row("only")])["windows"]["development"]["retained"]
    assert report["hit_rate"] == 1.0
    assert report["hit_rate_wilson_95"][0] < .80
    assert report["settled"] == 1
