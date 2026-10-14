"""Shared read-only Identity V2 gateway for source adapters and A/B linkers.

This is the ONLY research entrypoint for staged source-native events in the
new pipeline. Existing canonical writers and production importers are
intentionally NOT patched or silently routed through it; a separate planned
migration needs an authoritative witness, snapshot/NULL/rights gates.

An unambiguous candidate here is NOT independently verified or write eligible.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from scripts.research import identity_v2 as identity
from scripts.research import identity_v2_adapters as adapters
from scripts.research import identity_v2_triage as triage


@dataclass(frozen=True)
class GatewayResult:
    state: str
    candidates: tuple[identity.EventCandidate, ...]
    blockers: tuple[str, ...]
    identity_verified: bool = False
    cdb_write_authorized: bool = False


_ALWAYS = (
    "independent_provider_event_and_both_players_missing",
    "current_full_cdb_null_review_missing",
    "source_licence_or_rights_unverified",
    "point_in_time_not_attested",
)


def stage_sackmann(row, *, tour: str, collection: str, source_file_sha256: str,
                   line_number: int) -> adapters.Adapted:
    result = adapters.from_sackmann(
        row, tour=tour, collection=collection,
        file_sha256=source_file_sha256, line_number=line_number)
    return adapters.require_source_only(result)


def stage_season(row, *, tour: str, collection: str, source_file_sha256: str,
                 line_number: int) -> adapters.Adapted:
    result = adapters.from_season(
        row, tour=tour, collection=collection,
        file_sha256=source_file_sha256, line_number=line_number)
    return adapters.require_source_only(result)


def stage_native(row, *, source_name: str, tour: str, collection: str,
                 source_file_sha256: str, line_number: int,
                 field_map=None, date_kind: str = "played") -> adapters.Adapted:
    return adapters.require_source_only(adapters.from_native_event(
        row, source_name=source_name, tour=tour, collection=collection,
        file_sha256=source_file_sha256, line_number=line_number,
        field_map=field_map, date_kind=date_kind))


def stage_canonical_context(row) -> adapters.Adapted:
    return adapters.require_source_only(adapters.from_cdb_metadata(row))


def discover(source: identity.Event, canonical_context: Iterable[identity.Event],
             *, max_context_rows: int = 1000) -> GatewayResult:
    """Bounded, read-only query. No auto-accept path, even for unique matches."""
    if not 1 <= max_context_rows <= 10000:
        raise ValueError("Invalid bounded research context")
    context = tuple(canonical_context)
    if len(context) > max_context_rows:
        return GatewayResult("source_context_overflow_quarantined", (),
                             (*_ALWAYS,"too_many_candidate_context_rows"))
    if len({(x.namespace,x.event_id) for x in context}) != len(context):
        raise ValueError("Duplicate canonical context identities")
    found = tuple(identity.discover_events(source,context))
    if not identity.no_write_contract(found):
        raise AssertionError("Research candidate attempted to authorize CDB")
    if not found:
        return GatewayResult("no_research_match", (), _ALWAYS)
    blockers = set(_ALWAYS)
    if len(found) > 1:
        blockers.add("multiple_possible_canonical_events")
        state = "research_ambiguous_quarantined"
    elif found[0].context_tier != "edition_context_strong":
        blockers.add("tournament_edition_unresolved")
        state = "research_unique_weak_context"
    else:
        state = "research_unique_strong_context"
    return GatewayResult(state,found,tuple(sorted(blockers)))


def compare_baseline(source: identity.Event, canonical_context: Iterable[identity.Event],
                     old_proxy, *, max_context_rows: int = 1000
                     ) -> tuple[GatewayResult, triage.ReviewCase]:
    """Share one discovery route across historical A/B and importer research."""
    context = tuple(canonical_context)
    result = discover(source,context,max_context_rows=max_context_rows)
    if result.state == "source_context_overflow_quarantined":
        raise ValueError("A/B comparison cannot treat overflow as a no-match")
    old = [event for event in context if old_proxy(source,event)]
    review = triage.review_case(source,old,result.candidates)
    if review.independently_verified or review.cdb_write_authorized:
        raise AssertionError("A/B research cannot verify canonical identity")
    return result,review
