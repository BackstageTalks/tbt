"""Fail-closed linker for Valuebetennis CC BY 4.0 opening/closing odds.

Read-only: links downloaded CSV rows to canonical history and emits a stage file.
Closing prices are validation-only and never eligible as pre-match model features.
"""
from __future__ import annotations

import argparse, csv, hashlib, json
from collections import Counter, defaultdict
from datetime import timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_snapshot import load_partitions
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.offline_market_history import (
    build_market_history_marker, candidate_link, parse_valuebet_row,
)
from tbt.data.offline_odds import norm_surface, norm_text, tournament_score


def _signature(match):
    return {
        "tour": str(match.tour or "").lower(),
        "scheduled_date_utc": match.scheduled_at.astimezone(timezone.utc).date().isoformat(),
        "player1_id": str(match.player1_id), "player1_name": str(match.player1_name),
        "player2_id": str(match.player2_id), "player2_name": str(match.player2_name),
        "surface": str(match.surface or ""), "tournament": str(match.tournament or ""),
        "round_name": str(match.round_name or ""), "winner_id": str(match.winner_id or ""),
    }


def _winner_name(match):
    if str(match.winner_id or "") == str(match.player1_id): return str(match.player1_name or "")
    if str(match.winner_id or "") == str(match.player2_id): return str(match.player2_name or "")
    return ""


def _sha256(path):
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""): h.update(chunk)
    return h.hexdigest()


def _source_lookup(value):
    tokens = norm_text(value).split()
    if not tokens:
        return None
    cut = len(tokens)
    while cut > 0 and len(tokens[cut - 1]) == 1 and tokens[cut - 1].isalpha():
        cut -= 1
    if 0 < cut < len(tokens):
        return ("legacy", " ".join(tokens[:cut]))
    return ("exact", " ".join(tokens))


def _canonical_lookup_keys(value):
    normalized = norm_text(value)
    tokens = normalized.split()
    exact = {normalized} if normalized else set()
    legacy = set()
    for n in range(1, len(tokens)):
        legacy.add(" ".join(tokens[:n]))
        legacy.add(" ".join(tokens[-n:]))
    return exact, legacy


def _index_add(index, key, match):
    bucket = index[key]
    mid = str(match.match_id)
    if mid not in bucket:
        bucket[mid] = match


def _name_scored_candidates(source, by_exact_name, by_legacy_surname):
    lookup_a = _source_lookup(source.player_a)
    lookup_b = _source_lookup(source.player_b)
    if lookup_a is None or lookup_b is None:
        return []
    candidates = {}
    for delta in (-1, 0, 1):
        day = source.event_date + timedelta(days=delta)
        index_a = by_legacy_surname if lookup_a[0] == "legacy" else by_exact_name
        index_b = by_legacy_surname if lookup_b[0] == "legacy" else by_exact_name
        a = index_a.get((source.tour, day, lookup_a[1]), {})
        b = index_b.get((source.tour, day, lookup_b[1]), {})
        if not a or not b:
            continue
        for mid in a.keys() & b.keys():
            candidates[mid] = a[mid]
    scored = []
    for match in candidates.values():
        linked = candidate_link(
            source,
            canonical_tour=match.tour,
            canonical_date=match.scheduled_at.date(),
            canonical_player1=match.player1_name,
            canonical_player2=match.player2_name,
            canonical_winner=_winner_name(match),
            canonical_tournament=match.tournament,
            canonical_surface=match.surface,
            canonical_round=match.round_name,
        )
        if linked.get("score", -100) > -100:
            scored.append((int(linked["score"]), bool(linked["accepted"]), match, linked))
    scored.sort(key=lambda row: row[0], reverse=True)
    return scored


def _unique_accepted(scored):
    if not scored:
        return None
    top_score = scored[0][0]
    top = [row for row in scored if row[0] == top_score]
    if len(top) != 1 or not top[0][1]:
        return None
    return top[0]


def _strict_one_to_one_crosswalk(observations):
    forward = defaultdict(set)
    reverse = defaultdict(set)
    for tour, source_player_id, canonical_player_id in observations:
        source_key = (str(tour), str(source_player_id))
        canonical_key = (str(tour), str(canonical_player_id))
        if source_key[1] and canonical_key[1]:
            forward[source_key].add(canonical_key[1])
            reverse[canonical_key].add(source_key[1])
    result = {}
    for source_key, canonical_ids in forward.items():
        if len(canonical_ids) != 1:
            continue
        canonical_id = next(iter(canonical_ids))
        if len(reverse[(source_key[0], canonical_id)]) != 1:
            continue
        result[source_key] = canonical_id
    return result


def _orient_market(value, orientation):
    if value is None:
        return None
    if orientation == "direct":
        return dict(value)
    return {
        "player1_odds": value["player2_odds"],
        "player2_odds": value["player1_odds"],
        "player1_implied_probability": value["player2_implied_probability"],
        "player2_implied_probability": value["player1_implied_probability"],
        "raw_overround": value["raw_overround"],
    }


def _crosswalk_link(source, match, crosswalk):
    a = crosswalk.get((source.tour, str(source.player_a_id)))
    b = crosswalk.get((source.tour, str(source.player_b_id)))
    if not a or not b or a == b:
        return None
    p1, p2 = str(match.player1_id), str(match.player2_id)
    if {a, b} != {p1, p2}:
        return None
    if match.scheduled_at.date() != source.event_date:
        return None
    orientation = "direct" if (a, b) == (p1, p2) else "reversed"
    source_winner_id = (
        str(source.player_a_id)
        if source.winner == source.player_a
        else str(source.player_b_id)
    )
    mapped_winner = crosswalk.get((source.tour, source_winner_id))
    if not mapped_winner or mapped_winner != str(match.winner_id or ""):
        return None
    source_surface = norm_surface(source.surface)
    target_surface = norm_surface(match.surface)
    if (
        source_surface not in {"", "unknown"}
        and target_surface not in {"", "unknown"}
        and source_surface != target_surface
    ):
        return None
    tournament_points, tournament_evidence = tournament_score(
        source.tournament, match.tournament
    )
    if tournament_points <= 0:
        return None
    evidence = ["player_id_crosswalk", "date_exact", "winner_id", tournament_evidence]
    if source_surface not in {"", "unknown"} and target_surface not in {"", "unknown"}:
        evidence.append("surface")
    return {
        "accepted": True,
        "score": 20 + int(tournament_points),
        "evidence": evidence,
        "orientation": orientation,
        "opening": _orient_market(source.opening, orientation),
        "closing": _orient_market(source.closing, orientation),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--source-csv", action="append", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source-label", default="valuebetennis_cc_by_4")
    args = ap.parse_args()
    out = Path(args.out_dir); out.mkdir(parents=True, exist_ok=True)

    matches, safety = sanitize_history_identities(load_partitions(args.history_dir))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical history has identity quarantine; refusing market linking")

    by_exact_name = defaultdict(dict)
    by_legacy_surname = defaultdict(dict)
    by_player_ids = defaultdict(dict)
    for m in matches:
        base = (str(m.tour or "").lower(), m.scheduled_at.date())
        for player_name in (m.player1_name, m.player2_name):
            exact_keys, legacy_keys = _canonical_lookup_keys(player_name)
            for key in exact_keys:
                _index_add(by_exact_name, (*base, key), m)
            for key in legacy_keys:
                _index_add(by_legacy_surname, (*base, key), m)
        pair = frozenset((str(m.player1_id), str(m.player2_id)))
        _index_add(by_player_ids, (*base, pair), m)

    observations = []
    for filename in args.source_csv:
        path = Path(filename)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for number, raw in enumerate(csv.DictReader(handle, delimiter=";"), start=2):
                source = parse_valuebet_row(raw, row_number=number)
                if source is None:
                    continue
                best = _unique_accepted(
                    _name_scored_candidates(source, by_exact_name, by_legacy_surname)
                )
                if best is None:
                    continue
                _, _, match, linked = best
                if linked["orientation"] == "direct":
                    pairs = (
                        (source.player_a_id, match.player1_id),
                        (source.player_b_id, match.player2_id),
                    )
                else:
                    pairs = (
                        (source.player_a_id, match.player2_id),
                        (source.player_b_id, match.player1_id),
                    )
                observations.extend(
                    (source.tour, source_id, canonical_id)
                    for source_id, canonical_id in pairs
                )
    player_crosswalk = _strict_one_to_one_crosswalk(observations)

    counts, staged, review, quarantine = Counter(), [], [], []
    counts["player_id_crosswalk_entries"] = len(player_crosswalk)
    seen_source_ids = set()
    staged_by_match_id = {}
    for filename in args.source_csv:
        path = Path(filename); sha = _sha256(path)
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            for number, raw in enumerate(csv.DictReader(handle, delimiter=";"), start=2):
                counts["source_rows"] += 1
                source = parse_valuebet_row(raw, row_number=number)
                if source is None:
                    counts["invalid_source_rows"] += 1; continue
                key = (source.source_match_id, sha)
                if key in seen_source_ids:
                    counts["duplicate_source_rows"] += 1; continue
                seen_source_ids.add(key)
                scored = _name_scored_candidates(
                    source, by_exact_name, by_legacy_surname
                )
                chosen = _unique_accepted(scored)

                if chosen is None:
                    mapped_a = player_crosswalk.get(
                        (source.tour, str(source.player_a_id))
                    )
                    mapped_b = player_crosswalk.get(
                        (source.tour, str(source.player_b_id))
                    )
                    if mapped_a and mapped_b and mapped_a != mapped_b:
                        id_matches = by_player_ids.get(
                            (
                                source.tour,
                                source.event_date,
                                frozenset((mapped_a, mapped_b)),
                            ),
                            {},
                        )
                        recovered = []
                        for candidate in id_matches.values():
                            linked_by_id = _crosswalk_link(
                                source, candidate, player_crosswalk
                            )
                            if linked_by_id is not None:
                                recovered.append((candidate, linked_by_id))
                        if len(recovered) == 1:
                            m, linked = recovered[0]
                            chosen = (
                                int(linked["score"]),
                                True,
                                m,
                                linked,
                            )
                            counts["recovered_by_player_id_crosswalk"] += 1

                if chosen is None:
                    if not scored:
                        counts["unmatched"] += 1
                        continue
                    top_score = scored[0][0]
                    top = [row for row in scored if row[0] == top_score]
                    if len(top) != 1:
                        counts["ambiguous"] += 1
                        review.append({
                            "source_match_id": source.source_match_id,
                            "reason": "ambiguous",
                            "score": top_score,
                            "candidate_match_ids": [
                                str(row[2].match_id) for row in top
                            ],
                        })
                        continue
                    _, accepted, m, linked = top[0]
                    if not accepted:
                        counts["weak_evidence"] += 1
                        review.append({
                            "source_match_id": source.source_match_id,
                            "reason": "weak_evidence",
                            "candidate_match_id": str(m.match_id),
                            "score": linked["score"],
                            "evidence": linked["evidence"],
                        })
                        continue
                else:
                    _, accepted, m, linked = chosen
                marker = build_market_history_marker(source=source, linked=linked,
                    source_label=args.source_label, source_file_sha256=sha)
                existing = (m.provider_payload or {}).get("_tbt_market_history")
                if existing:
                    counts["already_present"] += 1
                    quarantine.append({"match_id": str(m.match_id), "source_match_id": source.source_match_id,
                                       "reason": "existing_market_history_preserved"})
                    continue
                stage_row = {"schema": 1, "match_id": str(m.match_id), "canonical": _signature(m),
                    "incoming_market_history": marker,
                    "source": {"row_number": number, "source_match_id": source.source_match_id,
                               "score": linked["score"], "evidence": linked["evidence"],
                               "orientation": linked["orientation"]}, "import_ready": True}
                match_key = str(m.match_id)
                previous = staged_by_match_id.get(match_key)
                if previous is not None:
                    counts["duplicate_canonical_links"] += 1
                    quarantine.append({"match_id": match_key,
                                       "source_match_ids": [previous["source"]["source_match_id"], source.source_match_id],
                                       "reason": "multiple_source_rows_link_same_canonical_match"})
                    if previous in staged:
                        staged.remove(previous)
                        counts["staged_matches"] -= 1
                    staged_by_match_id[match_key] = None
                    continue
                if match_key in staged_by_match_id:
                    counts["duplicate_canonical_links"] += 1
                    quarantine.append({"match_id": match_key, "source_match_id": source.source_match_id,
                                       "reason": "additional_source_row_for_quarantined_canonical_match"})
                    continue
                counts["staged_matches"] += 1
                staged.append(stage_row)
                staged_by_match_id[match_key] = stage_row

    report = {"schema": 1, "canonical_rows": len(matches), "counts": dict(counts),
              "production_mutated": False, "api_requests": 0,
              "license": "CC BY 4.0", "source": "Valuebetennis",
              "identity_recovery_policy": (
                  "strict one-to-one player-ID crosswalk learned only from already "
                  "accepted name links; exact-date pair + winner + surface/tournament "
                  "validation; conflicts remain fail-closed"
              ),
              "model_feature_policy": "opening_only_candidate; closing_validation_only"}
    (out/"report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, rows in (("auto_linked.jsonl", staged), ("review.jsonl", review), ("quarantine.jsonl", quarantine)):
        with (out/name).open("w", encoding="utf-8") as h:
            for row in rows: h.write(json.dumps(row, ensure_ascii=False)+"\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__": main()
