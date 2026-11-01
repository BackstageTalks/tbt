"""Current-board SG ingestion must stop asking paid questions once goals are met."""

from enrich_sg_history import _has_unmet_sg_target


def test_one_unmet_player_keeps_shared_match_eligible():
    coverage = {"p1": 18, "p2": 9, "p3": 2}
    assert _has_unmet_sg_target({"p1", "p2"}, coverage, 18)
    assert _has_unmet_sg_target({"p1", "p3"}, coverage, 18)


def test_surplus_matches_are_skipped_after_midrun_target_completion():
    coverage = {"p1": 18, "p2": 17, "p3": 3}
    assert _has_unmet_sg_target({"p1", "p2"}, coverage, 18)
    coverage["p2"] += 1  # Validated S/G row from an earlier candidate.
    assert not _has_unmet_sg_target({"p1", "p2"}, coverage, 18)
    assert _has_unmet_sg_target({"p2", "p3"}, coverage, 18)


def test_empty_participant_set_never_uses_api():
    assert not _has_unmet_sg_target(set(), {}, 24)
    assert not _has_unmet_sg_target({"p1"}, {"p1": 24}, 24)
