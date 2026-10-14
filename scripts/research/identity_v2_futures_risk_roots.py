"""Aggregate-only root-cause audit of 2025 ATP Futures research ambiguity.

A 28-day tournament-start search and surname/initial candidate search can
identify several *plausible* CDB events for one source match. This module
describes those collisions without choosing one, leaking match/player IDs,
granting provider crosswalks, approving data rights or writing to CDB.

Only the 2025 Sackmann ATP Futures old-unique -> new-ambiguous cohort is in
scope. Everything else is ignored. Aggregates reflect a pinned snapshot,
NOT current canonical facts or verified independent originals.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from typing import Iterable

from scripts.research import identity_v2 as ident

FUTURES_FAMILY = "atp/atp_matches_futures_2025.csv"
ALLOWED_TIER = {"edition_context_strong", "unresolved_event_edition"}


def _day(value: str) -> date:
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        raise ValueError("Cannot audit case with invalid source or CDB date")


def _exact_names(event: ident.Event) -> frozenset[str]:
    return frozenset(ident.exact_name_key(p.name) for p in event.players)


def inspect_case(source: ident.Event, old: list[ident.Event],
                 new: list[ident.EventCandidate],
                 context: Iterable[ident.Event]) -> dict:
    """Compute names-free, IDs-free flags; never resolve any canonical event."""
    if source.tour != "atp" or source.discipline != "singles":
        raise ValueError("Futures cohort must be ATP singles")
    if len(old) != 1 or len(new) <= 1:
        raise ValueError("Only old-unique -> new-ambiguous cases are audited")
    if any(x.identity_verified or x.cdb_write_authorized or
           x.context_tier not in ALLOWED_TIER for x in new):
        raise ValueError("Only unverified Identity V2 research candidates allowed")
    index: dict[str, ident.Event] = {}
    for candidate in context:
        if candidate.event_id in index:
            raise ValueError("Duplicate canonical context event identifier")
        index[candidate.event_id] = candidate
    ids = [x.canonical_event_id for x in new]
    if len(ids) != len(set(ids)) or not set(ids).issubset(index):
        raise ValueError("Duplicate/missing canonical research candidates")
    if old[0].event_id not in index:
        raise ValueError("Original old proxy event not found in context")
    start = _day(source.event_date)
    events = [index[n] for n in ids]
    deltas = [(_day(e.event_date)-start).days for e in events]
    if any(not 0 <= d <= 28 for d in deltas):
        raise ValueError("Out-of-window event in purported Futures candidate set")
    if any(e.tour != "atp" or e.discipline != "singles" for e in events):
        raise ValueError("Context contains out-of-scope events")
    exact_src = _exact_names(source)
    src_tour = ident.tournament_key(source.tournament)
    labels = [ident.tournament_key(e.tournament) for e in events]
    pairs = [_exact_names(e) for e in events]
    strongly = [x for x in new if x.context_tier=="edition_context_strong"]
    if source.date_kind != "tournament_start":
        raise ValueError("Expected original Sackmann tournament-start semantics")

    return {
        "old_event_retained": old[0].event_id in ids,
        "source_native_tournament_id_present": bool(source.edition_id),
        "source_round_present": bool(source.round_name),
        "source_score_present": bool(source.score),
        "source_all_names_full": all(len(p.name.split())>=2 and
                                     len(p.name.split()[-1])>1 and
                                     len(p.name.split()[0])>1 for p in source.players),
        "at_least_one_candidate_same_exact_pair": any(p==exact_src for p in pairs),
        "multiple_distinct_cdb_player_pairs": len(set(pairs))>1,
        "at_least_one_exact_tournament_label": bool(src_tour) and src_tour in labels,
        "multiple_distinct_cdb_tournament_labels": len(set(labels))>1,
        "all_candidate_labels_same": len(set(labels))==1,
        "multiple_distinct_cdb_scheduled_days": len(set(deltas))>1,
        "multiple_candidates_on_same_day": len(set(deltas))<len(deltas),
        "some_candidates_more_than_7_days_after_source_start": max(deltas)>7,
        "some_candidates_more_than_14_days_after_source_start": max(deltas)>14,
        "strong_context_count": len(strongly),
        "candidate_count": len(events),
        "canonical_event_resolved": False,
        "independent_provider_event_and_both_player_ids_attested": False,
        "cdb_write_authorized": False,
    }


@dataclass
class FuturesRiskCounter:
    observed: int = 0
    conditions: Counter = field(default_factory=Counter)
    candidate_bins: Counter = field(default_factory=Counter)
    strong_bins: Counter = field(default_factory=Counter)

    def consider(self, family: str, source: ident.Event, old: list[ident.Event],
                 new: list[ident.EventCandidate],
                 context: Iterable[ident.Event]) -> None:
        if family != FUTURES_FAMILY or len(old)!=1 or len(new)<=1:
            return
        result=inspect_case(source,old,new,context)
        self.observed+=1
        for key,value in result.items():
            if type(value) is bool and value:
                self.conditions[key]+=1
        count=result["candidate_count"]
        self.candidate_bins["2" if count==2 else "3" if count==3 else
                            "4-5" if count<=5 else "6+"]+=1
        strong=result["strong_context_count"]
        self.strong_bins["0" if strong==0 else "1" if strong==1 else "2+"]+=1

    def report(self) -> dict:
        return {
            "schema":"BLINQ_IDENTITY_V2_FUTURES_2025_AMBIGUITY_ROOT_AUDIT_V1",
            "scope":FUTURES_FAMILY,
            "old_unique_new_ambiguous_source_cases":self.observed,
            "condition_counts":dict(sorted(self.conditions.items())),
            "candidate_count_bins":dict(sorted(self.candidate_bins.items())),
            "strong_context_count_bins":dict(sorted(self.strong_bins.items())),
            "independently_verified_sackmann_to_cdb_event_links":0,
            "independently_verified_sackmann_to_cdb_player_links":0,
            "cdb_write_authorized":False,
            "cdb_writes":0,
            "source_provider_calls":0,
            "note":"Each condition is overlapping, not an exclusive cause or a validated identity. No automatic match selection.",
        }
