"""Why a broad research candidate was rejected while strict-name proxy found it.

Only DIAGNOSTIC hints; does not override the v2 matcher or grant identities.
No raw source/canonical rows in CI. Fail closed on unfamiliar shape.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable

from scripts.research import identity_v2 as v2
from scripts.research import shadow_identity_v2 as strict


def diagnose_old_only(source: v2.Event, old_candidate: v2.Event) -> str:
    if not strict.proxy_old_match(source,old_candidate):
        return "not_an_old_proxy_candidate"
    # Do not relabel an existing v2 candidate as an old-only loss.
    if v2.discover_events(source,[old_candidate]):
        return "not_lost_by_v2"
    pair_options=[]
    for order in ((0,1),(1,0)):
        fits=all(source.players[idx].names() & old_candidate.players[side].names()
                 for idx,side in enumerate(order))
        if fits:
            pair_options.append(order)
    if len(pair_options)!=1:
        return ("player_alias_pair_missing" if not pair_options
                else "player_side_orientation_ambiguous")
    order=pair_options[0]
    if source.namespace==old_candidate.namespace:
        if any(source.players[idx].native_id!=old_candidate.players[side].native_id
               for idx,side in enumerate(order)):
            return "same_namespace_player_id_conflict"
    if source.edition_id and old_candidate.edition_id and (
            source.namespace==old_candidate.namespace and
            source.edition_id!=old_candidate.edition_id):
        return "same_namespace_edition_conflict"
    if source.round_name and old_candidate.round_name and (
            v2.normalize_round(source.round_name)!=v2.normalize_round(
                old_candidate.round_name)):
        return "round_disagreement"
    if source.winner_native_id and old_candidate.winner_native_id:
        sw=next((i for i,p in enumerate(source.players)
                 if p.native_id==source.winner_native_id),None)
        cw=next((i for i,p in enumerate(old_candidate.players)
                 if p.native_id==old_candidate.winner_native_id),None)
        if sw is None or cw is None:
            return "winner_id_outside_player_pair"
        if order[sw]!=cw:
            return "winner_orientation_conflict"
    if source.score and old_candidate.score:
        ss,cs=v2.parse_score(source.score),v2.parse_score(old_candidate.score)
        if ss.valid and cs.valid:
            if (ss.status=="score_only")!=(cs.status=="score_only"):
                return "retirement_vs_completed_score_conflict"
            if ss.status=="score_only" and cs.status=="score_only":
                transformed=ss.sets if order==(0,1) else tuple(
                    (b,a) for a,b in ss.sets)
                if transformed!=cs.sets:
                    return "set_score_conflict"
    if source.draw and old_candidate.draw and source.draw!=old_candidate.draw:
        return "draw_disagreement"
    source_day=v2._day(source.event_date)
    target_day=v2._day(old_candidate.event_date)
    if source_day and target_day:
        days=(target_day-source_day).days
        if source.date_kind=="tournament_start" and (
                old_candidate.date_kind in ("scheduled","played")):
            if not 0<=days<=28:
                return "outside_tournament_start_window"
        elif abs(days)>1:
            return "outside_match_day_window"
    return "unexplained_candidate_loss_review_required"


def aggregate_old_only_diagnostics(
    cases: Iterable[tuple[v2.Event,list[v2.Event],list[v2.EventCandidate]]],
) -> dict:
    """Counts each old candidate rejected by v2, separately from source cases."""
    reasons=Counter()
    lost_source_cases=0
    examined_candidates=0
    for source,old,new in cases:
        if any(z.identity_verified or z.cdb_write_authorized for z in new):
            raise ValueError("Research diagnostics cannot accept authorized cases")
        observed={z.canonical_event_id for z in new}
        lost=[candidate for candidate in old if candidate.event_id not in observed]
        if lost:
            lost_source_cases+=1
        for candidate in lost:
            examined_candidates+=1
            reasons[diagnose_old_only(source,candidate)]+=1
    return {
        "schema":"BLINQ_IDENTITY_V2_OLD_CANDIDATE_REJECTION_V1",
        "source_cases_with_lost_candidates":lost_source_cases,
        "lost_old_candidates_examined":examined_candidates,
        "reason_counts":dict(sorted(reasons.items())),
        "canonical_identity_verified":False,
        "cdb_write_authorized":False,
        "notes":"Diagnostic categorization only; verify original provider event and both players.",
    }
