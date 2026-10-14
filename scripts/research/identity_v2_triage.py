"""Deterministic, privacy-preserving triage for BlinQ Identity V2 A/B candidates.

Never equate candidate set equality, exact name, source ID text, similar
tournament, winner/score context, or match counts with canonical verification.
Triage labels only tell independent reviewers WHERE to focus. All paths remain
research-only and CDB import prohibited.

This module emits coarse categories and safety blockers, not player names,
raw file rows, candidate identities, or provider/canonical IDs.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from scripts.research.identity_v2 import Event, EventCandidate


@dataclass(frozen=True)
class ReviewCase:
    bucket: str
    priority: int
    blockers: tuple[str, ...]
    old_count: int
    new_count: int
    independently_verified: bool = False
    cdb_write_authorized: bool = False


BUCKET_PRIORITIES = {
    "old_unique_became_ambiguous": 0,
    "old_unique_replaced": 1,
    "old_candidate_lost": 1,
    "old_ambiguous_changed": 2,
    "candidate_sets_disagree": 2,
    "new_only_ambiguous": 3,
    "new_only_unique_strong_context": 4,
    "new_only_unique_weak_context": 5,
    "old_ambiguous_now_unique": 5,
    "old_and_new_same_unique": 6,
    "old_and_new_same_ambiguous": 7,
    "no_candidate": 8,
}


def review_case(source: Event, old: Iterable[Event],
                new: Iterable[EventCandidate]) -> ReviewCase:
    """Measure changes without any implicit 'verified' or 'accepted' state."""
    old_list = tuple(old)
    new_list = tuple(new)
    if any(e.identity_verified or e.cdb_write_authorized for e in new_list):
        raise ValueError("Triage only supports unverified no-write candidate sets")
    old_ids = {e.event_id for e in old_list}
    new_ids = {e.canonical_event_id for e in new_list}
    if len(old_ids) != len(old_list) or len(new_ids) != len(new_list):
        # duplicate candidate IDs must not silently make a set appear unique
        raise ValueError("Duplicate event identifiers within A/B candidate set")
    unresolved_edition = any(e.context_tier != "edition_context_strong"
                             for e in new_list)
    blockers: set[str] = {
        "independent_event_and_both_players_crosswalk_missing",
        "source_rights_not_evaluated",
        "current_cdb_NULL_snapshot_not_rechecked",
        "point_in_time_not_proven",
    }
    if unresolved_edition and new_list:
        blockers.add("tournament_edition_unresolved")
    if len(new_list) > 1:
        blockers.add("multiple_event_candidates")
    if not source.round_name and new_list:
        blockers.add("source_round_missing")
    if not source.score and new_list:
        blockers.add("source_score_missing")
    if not source.winner_native_id and new_list:
        blockers.add("source_winner_unverified")
    if len(old_ids) == 1 and len(new_ids) > 1:
        bucket = "old_unique_became_ambiguous"
    elif len(old_ids) == 1 and len(new_ids) == 1 and old_ids != new_ids:
        bucket = "old_unique_replaced"
    elif old_ids and not new_ids:
        bucket = "old_candidate_lost"
    elif len(old_ids) > 1 and len(new_ids) == 1:
        bucket = "old_ambiguous_now_unique"
    elif len(old_ids) > 1 and new_ids != old_ids:
        bucket = "old_ambiguous_changed"
    elif old_ids and new_ids and old_ids != new_ids:
        bucket = "candidate_sets_disagree"
    elif not old_ids and len(new_ids) > 1:
        bucket = "new_only_ambiguous"
    elif not old_ids and len(new_ids) == 1:
        bucket = ("new_only_unique_strong_context" if
                  new_list[0].context_tier == "edition_context_strong"
                  else "new_only_unique_weak_context")
    elif not old_ids:
        bucket = "no_candidate"
    elif len(old_ids) == len(new_ids) == 1 and old_ids == new_ids:
        bucket = "old_and_new_same_unique"
    else:
        bucket = "old_and_new_same_ambiguous"
    return ReviewCase(bucket, BUCKET_PRIORITIES[bucket],
                      tuple(sorted(blockers)),len(old_ids),len(new_ids))


def safe_aggregate(cases: Iterable[ReviewCase]) -> dict:
    """Group-only metrics. No record keys/names/IDs in logged CI output."""
    from collections import Counter
    by_bucket: Counter = Counter()
    by_blocker: Counter = Counter()
    total = 0
    for case in cases:
        if case.independently_verified or case.cdb_write_authorized:
            raise ValueError("No promotion of unverified candidates")
        total += 1
        by_bucket[case.bucket] += 1
        by_blocker.update(case.blockers)
    return {
        "schema": "BLINQ_IDENTITY_V2_RESEARCH_TRIAGE_V1",
        "total_source_cases": total,
        "priority_bucket_counts": dict(sorted(by_bucket.items(),
                           key=lambda entry:(BUCKET_PRIORITIES[entry[0]],entry[0]))),
        "blocker_counts": dict(sorted(by_blocker.items())),
        "independent_canonical_event_attestations": 0,
        "cdb_import_authorized": False,
        "cdb_writes": 0,
        "note": "Review priority is not candidate accuracy or canonical identity proof.",
    }
