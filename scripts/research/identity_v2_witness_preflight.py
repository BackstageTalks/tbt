"""Independent ORIGINAL event evidence intake — identity-v2 REVIEW ONLY.

This is a shape/provenance consistency gate, not a trust oracle: a JSON witness
can be forged, a SHA only pins bytes, and independent upstream provenance has
to be checked externally. In particular, Sackmann file-row coordinates are
NOT provider-issued event IDs. The output never verifies canonical identity,
licenses a source or permits a CDB write.

Consistent with scripts/verify_tml_event_witnesses.py and
tbt-data/scripts/research/reconcile_l2_identity_bridges.py.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Iterable, Mapping
import re

from scripts.research import identity_v2 as v2

SHA = re.compile(r"^[0-9a-f]{64}$")


@dataclass(frozen=True)
class WitnessReview:
    status: str
    blockers: tuple[str, ...]
    identity_verified: bool = False
    canonical_match_attested: bool = False
    cdb_write_authorized: bool = False


def _text(row: Mapping, key: str) -> str:
    value=row.get(key)
    return value.strip() if isinstance(value,str) else ""


def _pair(row: Mapping, name: str) -> tuple[str,str]:
    raw=row.get(name)
    if (not isinstance(raw,list) or len(raw)!=2
            or any(not isinstance(x,str) or not x.strip() for x in raw)):
        raise ValueError("Witness requires explicit two-sided IDs: "+name)
    pair=(raw[0].strip(),raw[1].strip())
    if pair[0]==pair[1]:
        raise ValueError("Witness native player ID collision: "+name)
    return pair


def _source_pair(source: v2.Event) -> tuple[str,str]:
    return source.players[0].native_id,source.players[1].native_id


def _canonical_pair(target: v2.Event) -> tuple[str,str]:
    return target.players[0].native_id,target.players[1].native_id


def check_witness_shape(source: v2.Event, canonical: v2.Event,
                        row: Mapping, *, pinned_source_sha256: str,
                        pinned_cdb_sha256: str) -> WitnessReview:
    """Validate explicit independently sourced event + BOTH player claims.

    Passing this function never establishes an actual independent witness,
    because it does not download/read the signed/official original itself.
    """
    common=("independent_original_file_validation_pending",
            "official_provider_ID_crosswalk_verification_pending",
            "source_rights_and_PIT_not_verified",
            "current_full_CDB_NULL_gate_not_checked")
    if not isinstance(row,Mapping):
        raise ValueError("Witness must be mapping")
    if row.get("write_authorized") is not False or (
            row.get("import_ready") is not False):
        raise ValueError("Witness cannot arrive pre-authorized")
    if row.get("schema")!=1 or row.get("kind")!="independent_original_event_witness":
        return WitnessReview("unsupported_witness_schema",common)
    sha_fields=("source_file_sha256","independent_original_sha256",
                "canonical_snapshot_sha256")
    if any(not SHA.fullmatch(_text(row,k)) for k in sha_fields):
        return WitnessReview("missing_immutable_source_provenance",common)
    if (pinned_source_sha256!=row["source_file_sha256"] or
            pinned_cdb_sha256!=row["canonical_snapshot_sha256"]):
        return WitnessReview("snapshot_sha_mismatch",common)
    if pinned_source_sha256==row["independent_original_sha256"]:
        return WitnessReview("same_source_bytes_not_independent",common)
    if not all((_text(row,"source_namespace")==source.namespace,
                _text(row,"source_event_key")==source.event_id,
                _text(row,"canonical_match_id")==canonical.event_id,
                _text(row,"canonical_tour")==canonical.tour==source.tour)):
        return WitnessReview("event_scope_or_target_mismatch",common)
    if (_text(row,"source_lineage")==_text(row,"original_lineage") or
            not _text(row,"source_lineage") or
            not _text(row,"original_lineage")):
        return WitnessReview("unproven_independent_upstream_lineage",common)
    if not _text(row,"provider_namespace") or not _text(row,"provider_event_id"):
        return WitnessReview("missing_official_provider_native_event_ID",common)
    if _text(row,"provider_namespace")==source.namespace:
        return WitnessReview("same_source_namespace_not_independent",common)
    if row.get("original_kind")!="official_provider_native_event_with_both_players":
        return WitnessReview("original_lacks_both_players_and_event_ID",common)
    if row.get("source_key_kind") not in ("source_file_row_coordinate",
                                           "source_provider_native_event"):
        return WitnessReview("source_ID_kind_unknown",common)
    if (row.get("source_key_kind")=="source_file_row_coordinate"
            and row.get("coordinate_to_official_event_bridge_attested") is not True):
        return WitnessReview("source_row_not_official_event_ID",common)
    for name in ("source_native_player_ids","official_provider_player_ids",
                 "canonical_player_ids"):
        try:
            _pair(row,name)
        except ValueError:
            return WitnessReview("both_player_native_IDs_not_attested",common)
    if _pair(row,"source_native_player_ids")!=_source_pair(source):
        return WitnessReview("source_player_pair_mismatch",common)
    provider_sides=_pair(row,"official_provider_player_ids")
    if not all(provider_sides):
        return WitnessReview("both_player_native_IDs_not_attested",common)
    if _pair(row,"canonical_player_ids")!=_canonical_pair(canonical):
        return WitnessReview("canonical_player_pair_mismatch",common)
    # Winner is a cross-source side claim; conflict is a hard negative.
    if source.winner_native_id and canonical.winner_native_id:
        source_w=next((i for i,p in enumerate(source.players)
                       if p.native_id==source.winner_native_id),None)
        target_w=next((i for i,p in enumerate(canonical.players)
                       if p.native_id==canonical.winner_native_id),None)
        if source_w is None or target_w is None or source_w!=target_w:
            return WitnessReview("winner_side_conflict",common)
    # The independent original played day must support the canonical match
    # timestamp, not a fuzzy start-of-tournament window.
    played=_text(row,"official_played_day")
    canonical_day=v2._day(canonical.event_date)
    try:
        original_day=date.fromisoformat(played)
    except ValueError:
        return WitnessReview("independent_original_played_day_missing",common)
    if canonical_day is None or abs((original_day-canonical_day).days)>1:
        return WitnessReview("official_event_day_conflicts_with_CDB",common)
    return WitnessReview("witness_shape_consistent_for_PRIVATE_review",common)


def aggregate_witness_graph(
    items: Iterable[tuple[v2.Event,v2.Event,Mapping]],
    *, pinned_source_sha256: str,pinned_cdb_sha256: str
) -> dict:
    """Aggregate only; quarantine reused source/provider/canonical IDs.

    Duplicate/native ID contradictions are flagged even if rows have plausible
    checksums. Passing this graph still leaves 0 canonical identity witnesses.
    """
    entries=list(items)
    if len(entries)>100000:
        raise ValueError("Evidence graph exceeds bounded 100000 rows")
    if not SHA.fullmatch(pinned_source_sha256) or not SHA.fullmatch(pinned_cdb_sha256):
        raise ValueError("Full pinned source and canonical SHA required")
    per_source=defaultdict(set)
    per_provider=defaultdict(set)
    per_canonical=defaultdict(set)
    source_player_map=defaultdict(set)
    counts=Counter()
    parsed=[]
    for source,canonical,row in entries:
        if not isinstance(row,Mapping):
            raise ValueError("Witness rows must be objects")
        result=check_witness_shape(source,canonical,row,
                                 pinned_source_sha256=pinned_source_sha256,
                                 pinned_cdb_sha256=pinned_cdb_sha256)
        parsed.append((source,canonical,row,result))
        if result.status!="witness_shape_consistent_for_PRIVATE_review":
            counts[result.status]+=1
            continue
        s=(source.namespace,source.event_id)
        p=(_text(row,"provider_namespace"),_text(row,"provider_event_id"))
        c=(canonical.namespace,canonical.event_id)
        per_source[s].add((p,c))
        per_provider[p].add(c)
        per_canonical[c].add(p)
        for sid,cid in zip(_source_pair(source),_canonical_pair(canonical)):
            source_player_map[(source.namespace,source.tour,sid)].add(cid)
    for source,canonical,row,result in parsed:
        if result.status!="witness_shape_consistent_for_PRIVATE_review":
            continue
        s=(source.namespace,source.event_id)
        p=(_text(row,"provider_namespace"),_text(row,"provider_event_id"))
        c=(canonical.namespace,canonical.event_id)
        if len(per_source[s])!=1 or len(per_provider[p])!=1 or len(per_canonical[c])!=1:
            counts["event_identity_graph_collision"]+=1
        elif any(len(source_player_map[(source.namespace,source.tour,sid)])!=1
                 for sid in _source_pair(source)):
            counts["player_crosswalk_graph_collision"]+=1
        else:
            counts["witness_shape_consistent_private_review_only"]+=1
    return {
        "schema":"BLINQ_IDENTITY_V2_ORIGINAL_EVENT_WITNESS_PREFLIGHT_V1",
        "source_claim_rows":len(entries),
        "status_counts":dict(sorted(counts.items())),
        "actual_independent_originals_byte_verified":0,
        "actual_provider_player_ID_bridges_verified":0,
        "verified_canonical_events":0,
        "cdb_writes":0,
        "cdb_import_authorized":False,
        "note":"Self-declared witness fields and SHAs are not official evidence validation.",
    }
