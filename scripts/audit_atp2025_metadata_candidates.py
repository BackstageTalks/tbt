"""Read-only current-CDB metadata diagnostics; never an identity mapping."""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import timedelta
from audit_uploaded_atp2025_current_cdb import dt, score_sets, numeric_stats, counts


def review(sources, canonicals):
    from link_uploaded_flashscore_verified import short_matches, norm

    daily = defaultdict(list)
    for m in canonicals:
        when = dt(m.get("scheduled_at"))
        if when and str(m.get("tour") or "").lower() == "atp":
            daily[when.date()].append(m)

    summary = Counter()
    used_targets = Counter()
    prospective_nulls = defaultdict(list)
    for source in sources:
        start = dt(source.get("start_time_utc"))
        if not start:
            summary["source_event_time_missing"] += 1
            continue
        possible = []
        # +/- 24h permits discovery of a possible match, NOT identity proof.
        for day in (start.date() - timedelta(days=1), start.date(),
                    start.date() + timedelta(days=1)):
            for match in daily.get(day, ()):
                actual = dt(match.get("scheduled_at"))
                if not actual or abs((actual - start).total_seconds()) > 86400:
                    continue
                p1, p2 = match.get("player1_name"), match.get("player2_name")
                orientations = []
                if short_matches(p1, source.get("winner_name")) and short_matches(p2, source.get("loser_name")):
                    orientations.append(True)
                if short_matches(p2, source.get("winner_name")) and short_matches(p1, source.get("loser_name")):
                    orientations.append(False)
                if len(orientations) != 1:
                    continue
                winner_p1 = orientations[0]
                if (not match.get("player1_id") or not match.get("player2_id")
                        or match["player1_id"] == match["player2_id"]):
                    continue
                if str(match.get("winner_id")) != str(
                        match["player1_id"] if winner_p1 else match["player2_id"]):
                    continue
                if str(match.get("surface") or "").lower() != str(source.get("surface") or "").lower():
                    continue
                if str(match.get("status") or "").lower() not in ("finished", "ended", "completed"):
                    continue
                possible.append((match, winner_p1, actual))
        if len(possible) != 1:
            summary["no_unique_cdb_metadata_candidate" if not possible
                    else "ambiguous_cdb_metadata_candidates"] += 1
            continue

        match, winner_p1, actual = possible[0]
        used_targets[str(match["match_id"])] += 1
        summary["unique_metadata_candidates_not_verified"] += 1
        gap = abs((actual - start).total_seconds())
        summary["metadata_same_exact_utc" if gap == 0 else "metadata_time_drift"] += 1
        if norm(source.get("tourney_name")) != norm(match.get("tournament")):
            summary["metadata_tournament_label_diff"] += 1
        values = score_sets(source.get("score"))
        if not values:
            summary["metadata_source_unproven_set_score"] += 1
            continue
        existing = numeric_stats(match)
        if existing is None:
            summary["metadata_cdb_stats_invalid"] += 1
            continue
        score_ok = True
        for index, (w, l) in enumerate(values, 1):
            for side, games in (("p1", w if winner_p1 else l),
                                ("p2", l if winner_p1 else w)):
                stored = existing.get(f"{side}_set{index}_games")
                if (stored is None or not isinstance(stored, (int, float))
                        or isinstance(stored, bool) or float(stored) != games):
                    score_ok = False
        if not score_ok:
            summary["metadata_set_score_absent_or_conflict"] += 1
            continue
        summary["metadata_full_score_corroborated"] += 1
        derived = counts(source)
        if derived is None:
            summary["metadata_serve_source_invalid"] += 1
            continue
        incoming = {}
        for role, fields in (("w", derived["w"]), ("l", derived["l"])):
            prefix = "p1" if (role == "w") == winner_p1 else "p2"
            incoming.update({f"{prefix}_{key}": value for key, value in fields.items()})
        original = ("p1_aces", "p2_aces", "p1_double_faults", "p2_double_faults")
        if not all(isinstance(existing.get(key), (int, float))
                   and not isinstance(existing.get(key), bool)
                   and float(existing[key]) == float(incoming.get(key, float("nan")))
                   for key in original):
            summary["metadata_four_count_absent_or_conflict"] += 1
            continue
        summary["metadata_four_count_score_corroborated"] += 1
        conflicts = [key for key, value in incoming.items()
                     if existing.get(key) is not None
                     and (not isinstance(existing[key], (int, float))
                          or isinstance(existing[key], bool)
                          or abs(float(existing[key]) - float(value)) > 1e-6)]
        if conflicts:
            summary["metadata_other_cdb_stat_conflicts"] += 1
            continue
        summary["metadata_stats_consistent"] += 1
        prospective_nulls[str(match["match_id"])].append(
            sum(existing.get(key) is None for key in incoming)
        )
    collisions = sum(value > 1 for value in used_targets.values())
    summary["metadata_reused_cdb_target_groups_quarantined"] = collisions
    possible_nulls = sum(values[0] for mid, values in prospective_nulls.items()
                         if len(values) == 1 and used_targets[mid] == 1)
    return {
        "state": "METADATA_ONLY_UNVERIFIED_NO_AUTHORITATIVE_EVENT_OR_TWO_PLAYER_LINK",
        "counts": dict(sorted(summary.items())),
        "research_null_cells_not_authorized": possible_nulls,
        "canonical_links_authorized": 0,
        "import_ready": False,
        "cdb_writes": 0,
    }
