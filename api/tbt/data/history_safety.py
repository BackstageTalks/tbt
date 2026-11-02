from __future__ import annotations

"""Deterministic safety layer for legacy/corrupted history identities.

The strict audit remains fail-closed. This module is used *before* the audit to
merge rows that are provably the same provider event and quarantine identity
collisions that cannot be resolved without guessing. Quarantined rows are
excluded from model/prediction input and must be reported to the operator.
"""

from collections import Counter
from typing import Iterable

from tbt.schemas import MatchRecord
from .history_snapshot import merge_matches, _provider_event_id


def _identity_tuple(match: MatchRecord) -> tuple:
    return (
        str(match.match_id or ""),
        str(_provider_event_id(match) or ""),
        match.scheduled_at.isoformat(),
        str(match.tour or "").lower(),
        str(match.player1_id or ""),
        str(match.player2_id or ""),
        str(match.winner_id or ""),
    )


def _identity_counter(matches: Iterable[MatchRecord]) -> Counter:
    return Counter(_identity_tuple(match) for match in matches)


def _duplicates(values: Iterable[str]) -> set[str]:
    counts = Counter(value for value in values if value)
    return {value for value, count in counts.items() if count > 1}


def _changed_years(before: list[MatchRecord], after: list[MatchRecord]) -> list[int]:
    years = {
        int(match.scheduled_at.year)
        for match in [*before, *after]
    }
    changed = []
    for year in sorted(years):
        left = _identity_counter(match for match in before if int(match.scheduled_at.year) == year)
        right = _identity_counter(match for match in after if int(match.scheduled_at.year) == year)
        if left != right:
            changed.append(year)
    return changed


def quarantine_budget(
    input_rows: int,
    *,
    ratio: float = 0.001,
    minimum: int = 20,
    maximum: int = 500,
) -> int:
    """Small-corruption tolerance; large losses fail closed instead of deleting data."""
    calculated = max(int(minimum), int(round(max(0, input_rows) * max(0.0, ratio))))
    return min(int(maximum), calculated)


def sanitize_history_identities(matches: Iterable[MatchRecord]) -> tuple[list[MatchRecord], dict]:
    """Return model-safe history plus a deterministic identity repair report.

    1. ``merge_matches`` merges records only where identity evidence is strong.
    2. Any duplicate match id or provider-event id still remaining is ambiguous.
       Every row in that collision is quarantined rather than guessed.
    3. The strict downstream ``audit_history`` can therefore remain fail-closed.
    """
    original = list(matches)
    merged = merge_matches(original)

    duplicate_match_ids = _duplicates(str(m.match_id or "") for m in merged)
    duplicate_provider_event_ids = _duplicates(
        str(_provider_event_id(m) or "") for m in merged
    )

    quarantined: list[MatchRecord] = []
    safe: list[MatchRecord] = []
    for match in merged:
        match_id = str(match.match_id or "")
        provider_id = str(_provider_event_id(match) or "")
        if match_id in duplicate_match_ids or (
            provider_id and provider_id in duplicate_provider_event_ids
        ):
            quarantined.append(match)
        else:
            safe.append(match)

    safe.sort(key=lambda item: (item.scheduled_at, str(item.match_id)))
    quarantined.sort(key=lambda item: (item.scheduled_at, str(item.match_id)))

    affected_years = _changed_years(original, safe)
    changed = bool(affected_years)
    quarantine_count = len(quarantined)
    report = {
        "schema": 2,
        "input_rows": len(original),
        "rows_after_proven_merges": len(merged),
        "output_rows": len(safe),
        "merged_rows_removed": max(0, len(original) - len(merged)),
        "quarantined_rows": quarantine_count,
        "quarantine_rate": (quarantine_count / len(original)) if original else 0.0,
        "duplicate_match_ids": sorted(duplicate_match_ids),
        "duplicate_provider_event_ids": sorted(duplicate_provider_event_ids),
        "affected_years": affected_years,
        "changed": changed,
        "quarantine": [
            {
                "match_id": str(m.match_id or ""),
                "provider_event_id": str(_provider_event_id(m) or ""),
                "scheduled_at": m.scheduled_at.isoformat(),
                "tour": str(m.tour or ""),
                "tournament": str(m.tournament or ""),
                "player1_id": str(m.player1_id or ""),
                "player2_id": str(m.player2_id or ""),
                "winner_id": str(m.winner_id or ""),
                "reason": "ambiguous_duplicate_identity",
            }
            for m in quarantined
        ],
    }
    return safe, report



def select_exact_provider_quarantine(
    matches: Iterable[MatchRecord],
    *, expected_rows: int = 0, preserve_quarantined: bool = False,
) -> tuple[list[MatchRecord], dict, set[str]]:
    """Fail closed on unexpected CDB collisions; optionally retain protected rows.

    Linkers see only safe rows. Exact-stats writers must see every original
    row so full-year Parquet readback proves the quarantined rows unchanged.
    No provider identity is guessed, merged, removed, or overwritten.
    """
    original = list(matches)
    safe, report = sanitize_history_identities(original)
    if isinstance(expected_rows, bool) or not isinstance(expected_rows, int) or expected_rows < 0:
        raise ValueError("Invalid exact provider quarantine expectation")
    if report["quarantined_rows"] != expected_rows:
        raise ValueError(
            f"Unexpected canonical identity quarantine: "
            f"{report['quarantined_rows']} != {expected_rows}"
        )
    protected_ids: set[str] = set()
    if expected_rows:
        protected = report["quarantine"]
        protected_ids = {str(row["match_id"]) for row in protected}
        all_ids = [str(m.match_id) for m in original]
        provider_ids = set(report["duplicate_provider_event_ids"])
        if (
            report["merged_rows_removed"] != 0
            or report["duplicate_match_ids"]
            or len(safe) + expected_rows != len(original)
            or len(protected_ids) != expected_rows
            or len(set(all_ids)) != len(all_ids)
            or not protected_ids.issubset(set(all_ids))
            or not provider_ids
            or any(str(row["provider_event_id"]) not in provider_ids for row in protected)
        ):
            raise ValueError("Quarantine is not exact, lossless provider-only isolation")
    return (original if preserve_quarantined and expected_rows else safe), report, protected_ids

def merge_trusted_history_batch(
    existing: Iterable[MatchRecord],
    incoming: Iterable[MatchRecord],
) -> tuple[list[MatchRecord], list[MatchRecord], dict]:
    """Merge a provider batch while preserving already-audited canonical history.

    Existing history is assumed to have passed repair/audit. If the incoming
    batch creates an unresolved match/provider identity collision, only the
    conflicting incoming rows are quarantined. Existing canonical rows are
    preserved. This makes one bad provider event non-fatal without guessing.
    """
    from .history_snapshot import _canonical_match_id

    trusted = list(existing)
    additions = list(incoming)
    # The private canonical release can already contain conflicting claims
    # about one provider event ID (e.g. three 2026 ITF pairs). Preserve their
    # exact original rows and isolate them from the provider merge. Do NOT
    # silently delete these six rows: CDB's row-monotonicity gate forbids it.
    protected_ids = _duplicates(str(m.match_id or "") for m in trusted)
    protected_provider_ids = _duplicates(
        str(_provider_event_id(m) or "") for m in trusted
    )
    if protected_ids or protected_provider_ids:
        protected, clean = [], []
        for match in trusted:
            pid = str(_provider_event_id(match) or "")
            (protected if (
                str(match.match_id or "") in protected_ids
                or (pid and pid in protected_provider_ids)
            ) else clean).append(match)

        # Never accept an incoming claim against a protected identity,
        # including its canonical fallback ID. Review is required to decide
        # which of the original provider claims is authentic.
        protected_canonical_ids = {
            str(_canonical_match_id(m) or "") for m in protected
        }
        protected_match_ids = {str(m.match_id or "") for m in protected}
        rejected, eligible = [], []
        for match in additions:
            pid = str(_provider_event_id(match) or "")
            ids = {str(match.match_id or ""), str(_canonical_match_id(match) or "")}
            if ((pid and pid in protected_provider_ids)
                    or bool(ids & (protected_match_ids | protected_canonical_ids))):
                rejected.append(match)
            else:
                eligible.append(match)
        merged_clean, accepted, incoming_report = merge_trusted_history_batch(clean, eligible)
        if len(merged_clean) < len(clean):
            raise ValueError("Existing CDB clean rows would shrink; refuse provider write")
        result = sorted([*protected, *merged_clean],
                        key=lambda row: (row.scheduled_at, str(row.match_id)))
        if len(result) < len(trusted):
            raise ValueError("Existing CDB rows would shrink; refuse provider write")
        details = [{
            "match_id": str(m.match_id or ""),
            "canonical_match_id": str(_canonical_match_id(m) or ""),
            "provider_event_id": str(_provider_event_id(m) or ""),
            "scheduled_at": m.scheduled_at.isoformat(),
            "tour": str(m.tour or ""), "tournament": str(m.tournament or ""),
            "player1_id": str(m.player1_id or ""),
            "player2_id": str(m.player2_id or ""),
            "reason": "incoming_hits_preexisting_cdb_identity_quarantine",
        } for m in rejected]
        return result, accepted, {
            "schema": 1,
            "quarantined_rows": len(details) + int(incoming_report["quarantined_rows"]),
            "rows": details + list(incoming_report.get("rows") or []),
            "protected_existing_rows": len(protected),
            "protected_existing_provider_id_collisions": len(protected_provider_ids),
            "collision": {
                "existing_duplicate_match_ids": sorted(protected_ids),
                "existing_duplicate_provider_event_ids": sorted(protected_provider_ids),
                "incoming": incoming_report.get("collision"),
            },
        }
    merged = merge_matches(trusted, additions)
    safe, report = sanitize_history_identities(merged)
    if not report.get("quarantined_rows"):
        return safe, additions, {
            "schema": 1,
            "quarantined_rows": 0,
            "rows": [],
            "collision": report,
        }

    duplicate_match_ids = set(report.get("duplicate_match_ids") or [])
    duplicate_provider_ids = set(report.get("duplicate_provider_event_ids") or [])

    def conflicts(match: MatchRecord) -> bool:
        provider_id = str(_provider_event_id(match) or "")
        ids = {str(match.match_id or ""), str(_canonical_match_id(match) or "")}
        return bool(ids & duplicate_match_ids) or bool(
            provider_id and provider_id in duplicate_provider_ids
        )

    quarantined_incoming = [match for match in additions if conflicts(match)]
    accepted_incoming = [match for match in additions if not conflicts(match)]

    rebuilt = merge_matches(trusted, accepted_incoming)
    rebuilt, post = sanitize_history_identities(rebuilt)
    if post.get("quarantined_rows"):
        raise ValueError("Ambiguous history identity remains after incoming quarantine")

    details = [
        {
            "match_id": str(match.match_id or ""),
            "canonical_match_id": str(_canonical_match_id(match) or ""),
            "provider_event_id": str(_provider_event_id(match) or ""),
            "scheduled_at": match.scheduled_at.isoformat(),
            "tour": str(match.tour or ""),
            "tournament": str(match.tournament or ""),
            "player1_id": str(match.player1_id or ""),
            "player2_id": str(match.player2_id or ""),
            "reason": "incoming_ambiguous_identity_collision",
        }
        for match in quarantined_incoming
    ]
    return rebuilt, accepted_incoming, {
        "schema": 1,
        "quarantined_rows": len(details),
        "rows": details,
        "collision": {
            "duplicate_match_ids": sorted(duplicate_match_ids),
            "duplicate_provider_event_ids": sorted(duplicate_provider_ids),
        },
    }
