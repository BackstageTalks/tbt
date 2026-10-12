#!/usr/bin/env python3
"""Private read-only revalidation of official ATP player IDs and TML event context.

Consumes an immutable 186-ID *review* sidecar, older verified ATP player links,
the original SHA-pinned TML observation lake, and fresh checksum-verified
canonical CDB year partitions. No implied native event ID equality: TML dates
are tournament-week start dates, and metadata matches are REVIEW ONLY.
Never creates canonical match identity witnesses, staging import_ready rows,
canonical writes, model changes, provider calls, or public row artifacts.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import unicodedata

YEAR_RANGE = range(2022, 2026)
SHA = re.compile(r"^[a-f0-9]{64}$")
ATP = re.compile(r"^[A-Za-z0-9]{2,32}$")
MAX_BYTES = 70 * 1024 * 1024
MAX_ROWS = 100000
FIELDS = ["match_id", "tour", "scheduled_at", "player1_id", "player2_id",
          "player1_name", "player2_name", "winner_id", "tournament",
          "round_name", "surface", "best_of", "status", "stats_json"]


def norm(value):
    t = unicodedata.normalize("NFKD", str(value or "").casefold())
    return " ".join(re.findall(r"[a-z0-9]+", "".join(
        c for c in t if not unicodedata.combining(c))))


# Only semantically identical, provider-independent draw round labels.
ROUND_ALIASES = {
    "f": "f", "final": "f", "finals": "f",
    "sf": "sf", "semifinal": "sf", "semifinals": "sf",
    "semi final": "sf", "semi finals": "sf",
    "qf": "qf", "quarterfinal": "qf", "quarterfinals": "qf",
    "quarter final": "qf", "quarter finals": "qf",
    "r128": "r128", "round of 128": "r128",
    "r64": "r64", "round of 64": "r64",
    "r32": "r32", "round of 32": "r32",
    "r16": "r16", "round of 16": "r16",
    "rr": "rr", "round robin": "rr",
    "q1": "q1", "1st round qualifying": "q1", "first round qualifying": "q1",
    "q2": "q2", "2nd round qualifying": "q2", "second round qualifying": "q2",
    "q3": "q3", "3rd round qualifying": "q3", "third round qualifying": "q3",
}


def canonical_round(value):
    label = norm(value)
    return ROUND_ALIASES.get(label, label)


def sha_file(path: Path, expected: str):
    if not SHA.fullmatch(str(expected)):
        raise ValueError("A full expected SHA-256 is mandatory")
    if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_BYTES:
        raise ValueError("Input absent, symlinked or oversized")
    h = hashlib.sha256()
    with path.open("rb") as src:
        for b in iter(lambda: src.read(1024 * 1024), b""):
            h.update(b)
    if h.hexdigest() != expected:
        raise ValueError("Pinned input digest mismatch")
    return expected


def read_jsonl(path: Path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as src:
        for i, line in enumerate(src):
            if i >= MAX_ROWS:
                raise ValueError("Too many private JSONL rows")
            if line.strip():
                val = json.loads(line, parse_constant=lambda x: (
                    _ for _ in ()).throw(ValueError("Invalid NaN/Infinity")))
                if not isinstance(val, dict):
                    raise ValueError("Expected JSONL dictionary")
                yield val


def canonical_rows(history_dir: Path):
    """Read only four selected canonical years after pinned bundle SHA checks."""
    import pandas as pd
    raw = (history_dir / "_tbt_bundle_manifest.json").read_bytes()
    bundle = json.loads(raw)
    files = bundle.get("files")
    if not isinstance(files, dict):
        raise ValueError("Canonical bundle manifest missing files")
    entries = []
    digests = {}
    match_ids = set()
    for year in YEAR_RANGE:
        name = f"history-{year}.parquet"
        entry = files.get(name)
        expected = entry.get("sha256") if isinstance(entry, dict) else None
        path = history_dir / name
        # Private current CDB Parquet can exceed the small research input cap.
        if path.is_symlink() or not path.is_file() or path.stat().st_size > 512*1024*1024:
            raise ValueError("Missing or oversized canonical history partition")
        if not SHA.fullmatch(str(expected)):
            raise ValueError("Missing signed canonical year partition SHA")
        h = hashlib.sha256()
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                h.update(chunk)
        if h.hexdigest() != expected:
            raise ValueError("Canonical bundle partition SHA mismatch")
        frame = pd.read_parquet(path, columns=FIELDS)
        digests[name] = expected
        for record in frame.to_dict("records"):
            mid = str(record.get("match_id") or "")
            if not mid or mid in match_ids:
                raise ValueError("Missing or duplicate canonical match ID")
            match_ids.add(mid)
            if str(record.get("tour") or "").lower() != "atp":
                continue
            when = pd.to_datetime(record.get("scheduled_at"), utc=True, errors="coerce")
            if pd.isna(when) or when.year != year:
                raise ValueError("Invalid canonical UTC year")
            record["scheduled_day"] = when.date().isoformat()
            record["match_id"] = mid
            entries.append(record)
    return entries, digests


def valid_candidate_edges(proposals, legacy, cc0_links, matches):
    """Require exact official ATP ID, QID, canonical owner & fresh CDB name."""
    observed = defaultdict(set)
    for row in matches:
        for n in (1, 2):
            cid = str(row.get(f"player{n}_id") or "")
            label = norm(row.get(f"player{n}_name"))
            if cid and label:
                observed[cid].add(label)
    cc0 = defaultdict(set)
    for row in cc0_links:
        if (row.get("tour") != "atp" or row.get("source") != "Wikidata"
            or row.get("license") != "CC0-1.0"
            or row.get("evidence") !=
                "unique_exact_name_both_sides_plus_tour_specific_id"):
            continue
        data = row.get("external_ids") or {}
        for atp_id in data.get("atp") or []:
            if isinstance(atp_id, str) and ATP.fullmatch(atp_id):
                cc0[atp_id.upper()].add((
                    str(row.get("wikidata_qid") or ""),
                    str(row.get("player_id") or ""),
                    norm(row.get("canonical_name"))))
    original = defaultdict(set)
    for row in legacy:
        if (row.get("tour") == "atp"
                and row.get("source") == "BlinQ verified CDB plus Wikidata CC0"
                and row.get("evidence") ==
                    "official_atp_identifier_unique_registry_full_name_and_nonconflicting_cdb"):
            sid, cid = str(row.get("atp_tour_id") or ""), str(
                row.get("canonical_player_id") or "")
            cname = norm(row.get("canonical_name"))
            if ATP.fullmatch(sid) and cid and cname and observed.get(cid) == {cname}:
                original[sid.upper()].add(cid)
    counts = Counter()
    accepted = {}
    seen = set()
    for p in proposals:
        code = str(p.get("source_atp_player_id") or "").upper()
        if not ATP.fullmatch(code) or code in seen:
            raise ValueError("Malformed or duplicate player proposal ID")
        seen.add(code)
        if (p.get("import_ready") is not False or
                p.get("write_authorized") is not False or
                p.get("canonical_match_id") is not None or
                p.get("status") !=
                "REVIEW_ONLY_EVENT_AND_BOTH_SIDES_NOT_YET_ATTESTED"):
            raise ValueError("Unsafe preapproved ATP player proposal")
        qid = str(p.get("wikidata_qid") or "")
        cid = str(p.get("candidate_canonical_player_id") or "")
        matches_cc0 = cc0.get(code, set())
        if len(matches_cc0) != 1 or next(iter(matches_cc0))[:2] != (qid, cid):
            counts["blocked_ambiguous_cc0"] += 1
            continue
        cname = next(iter(matches_cc0))[2]
        if not cname or observed.get(cid) != {cname}:
            counts["blocked_stale_or_ambiguous_current_cdb_name"] += 1
            continue
        if original.get(code) and original[code] != {cid}:
            counts["blocked_legacy_id_conflict"] += 1
            continue
        accepted[code] = cid
        counts["fresh_player_id_bridge_review_candidates"] += 1
    # Re-validate the previously verified sidecar against same current CDB:
    # no silent override by newly reviewed IDs, no shared CDB player owner.
    for code, targets in original.items():
        if code not in accepted and len(targets) == 1:
            accepted[code] = next(iter(targets))
    reverse = defaultdict(set)
    for code, cid in accepted.items():
        reverse[cid].add(code)
    collisions = {cid for cid, codes in reverse.items() if len(codes) > 1}
    if collisions:
        accepted = {code: cid for code, cid in accepted.items()
                    if cid not in collisions}
        counts["blocked_shared_canonical_player_owners"] = len(collisions)
    return accepted, dict(counts)


def compare_core_service_cells(source_raw, canonical, winner_cid, loser_cid):
    """Count potential NULLs without treating metadata-only links as importable."""
    payload = canonical.get("stats_json")
    if isinstance(payload, str):
        payload = json.loads(payload, parse_constant=lambda x: (
            _ for _ in ()).throw(ValueError("Invalid numeric CDB stats")))
    if not isinstance(payload, dict):
        raise ValueError("Canonical stats JSON must contain a dictionary")
    res = Counter()
    for source_side, target_id in (("w", winner_cid), ("l", loser_cid)):
        if target_id == str(canonical.get("player1_id")):
            prefix = "p1"
        elif target_id == str(canonical.get("player2_id")):
            prefix = "p2"
        else:
            raise ValueError("Source player identity does not match canonical sides")
        for field, target_suffix in (("ace", "aces"), ("df", "double_faults")):
            raw = source_raw.get(f"{source_side}_{field}")
            if not isinstance(raw, str) or not raw.isascii() or not raw.isdecimal():
                res["unusable_source_core_stat_cells"] += 1
                continue
            value = int(raw)
            if value < 0 or value > 1000:
                res["unusable_source_core_stat_cells"] += 1
                continue
            key = f"{prefix}_{target_suffix}"
            old = payload.get(key)
            res["observed_source_core_stat_cells"] += 1
            if old is None or old == "":
                res["current_null_core_cells_review_only"] += 1
                continue
            if isinstance(old, bool):
                res["conflicting_core_stat_cells"] += 1
                continue
            try:
                parsed = float(old)
            except (TypeError, ValueError):
                res["conflicting_core_stat_cells"] += 1
                continue
            if not (parsed >= 0 and parsed.is_integer() and int(parsed) == value):
                res["conflicting_core_stat_cells"] += 1
            else:
                res["existing_core_stat_cells_equal"] += 1
    return dict(res)


def compare_derived_rates(source_raw, canonical, winner_cid, loser_cid,
                          core_proof):
    """Read-only derived serve/return potential, only if all 4 core cells agree.

    These are POSTMATCH research rates, never same-match prestart model inputs.
    Partial/conflicting aces or DF are not corroboration and block speculation.
    """
    counts = Counter()
    if (core_proof.get("observed_source_core_stat_cells") != 4
            or core_proof.get("existing_core_stat_cells_equal") != 4
            or core_proof.get("conflicting_core_stat_cells")
            or core_proof.get("unusable_source_core_stat_cells")):
        counts["rate_review_blocked_missing_four_core_equal_witnesses"] += 1
        return dict(counts)
    fields = {}
    for side in ("w", "l"):
        try:
            values = {key: int(source_raw[f"{side}_{key}"])
                      for key in ("svpt", "1stIn", "1stWon", "2ndWon")}
        except (TypeError, ValueError, KeyError):
            counts["rate_review_incomplete_source_boxscore"] += 1
            return dict(counts)
        if (any(v < 0 for v in values.values())
                or not (0 < values["svpt"] < 2000)
                or not (0 < values["1stIn"] <= values["svpt"])
                or values["1stWon"] > values["1stIn"]
                or values["2ndWon"] > values["svpt"] - values["1stIn"]):
            counts["rate_review_impossible_source_boxscore"] += 1
            return dict(counts)
        fields[side] = values
    raw_json = canonical.get("stats_json")
    stats = json.loads(raw_json) if isinstance(raw_json, str) else raw_json
    if not isinstance(stats, dict):
        raise ValueError("Canonical stats JSON must be a dictionary")
    rates = {}
    for side, cid, other in (("w", winner_cid, "l"),
                             ("l", loser_cid, "w")):
        v = fields[side]
        opp = fields[other]
        prefix = "p1" if cid == str(canonical.get("player1_id")) else "p2"
        second = v["svpt"] - v["1stIn"]
        if second <= 0:
            counts["rate_review_missing_second_serve_denominator"] += 1
            return dict(counts)
        current = {
            "first_serve_win": v["1stWon"] / v["1stIn"],
            "second_serve_win": v["2ndWon"] / second,
            "service_points_won": (v["1stWon"] + v["2ndWon"]) / v["svpt"],
            "return_points_won": (opp["svpt"] -
                                  opp["1stWon"] - opp["2ndWon"]) / opp["svpt"],
        }
        for field, value in current.items():
            if not 0 <= value <= 1:
                raise ValueError("Impossible derived postmatch rate")
            rates[prefix + "_" + field] = value
    for key, value in rates.items():
        old = stats.get(key)
        counts["observed_derived_rate_cells_review_only"] += 1
        if old is None or old == "":
            counts["potential_current_null_rate_cells_review_only"] += 1
        else:
            if isinstance(old, bool):
                counts["conflicting_derived_rate_cells"] += 1
                continue
            try:
                old_number = float(old)
            except (ValueError, TypeError):
                counts["conflicting_derived_rate_cells"] += 1
                continue
            if (old_number >= 0 and old_number <= 1 and
                    abs(old_number - value) <= 0.001):
                counts["existing_derived_rate_cells_equal_rounded"] += 1
            else:
                counts["conflicting_derived_rate_cells"] += 1
    return dict(counts)


def score_event_candidates(observations, current_matches, links):
    """Examine possible events, but NEVER claim a canonical event identity."""
    by_pair = defaultdict(list)
    for c in current_matches:
        ids = (str(c.get("player1_id") or ""), str(c.get("player2_id") or ""))
        if all(ids) and ids[0] != ids[1]:
            by_pair[frozenset(ids)].append(c)
    count = Counter()
    possible = []
    seen_native = set()
    source_rows = list(observations)
    for source in source_rows:
        if (source.get("schema") != 1
                or source.get("canonical_match_id") is not None
                or source.get("write_authorized") is not False
                or source.get("import_ready") is not False):
            raise ValueError("Source-only observation was preauthorized")
        count["source_rows_reviewed"] += 1
        if (source.get("linkage_status") !=
                "SOURCE_UNLINKED_ORIGINAL_IDS_PRESENT"
                or source.get("tour") != "atp"):
            count["blocked_incomplete_native_event"] += 1
            continue
        native = source.get("source_native_event_key")
        if not isinstance(native, list) or not native:
            count["blocked_missing_native_key"] += 1
            continue
        key = (source.get("source_namespace"), tuple(native))
        if key in seen_native:
            raise ValueError("Duplicate original source event key in evidence lake")
        seen_native.add(key)
        sid_w = str(source.get("source_winner_id") or "").upper()
        sid_l = str(source.get("source_loser_id") or "").upper()
        if not sid_w or not sid_l or sid_w == sid_l:
            count["blocked_incomplete_player_pair"] += 1
            continue
        wid, lid = links.get(sid_w), links.get(sid_l)
        if not wid or not lid or wid == lid:
            count["blocked_unverified_current_player_pair"] += 1
            continue
        count["both_player_ids_current_review_linked"] += 1
        raw = source.get("raw_columns") or {}
        try:
            tournament_start = datetime.strptime(
                str(source.get("source_date") or ""), "%Y%m%d").date()
        except ValueError:
            count["blocked_source_date"] += 1
            continue
        # Ordered rejection counters reveal the first unresolved context
        # without printing any player, provider ID, event, or raw source row.
        candidates = list(by_pair.get(frozenset((wid, lid)), []))
        steps = (
            ("source_tournament_week",
             lambda c: 0 <= (
                 datetime.fromisoformat(c["scheduled_day"]).date() -
                 tournament_start).days <= 16),
            ("canonical_winner_id",
             lambda c: str(c.get("winner_id") or "") == wid),
            ("exact_tournament_name",
             lambda c: norm(c.get("tournament")) == norm(raw.get("tourney_name"))),
            ("equivalent_round_name",
             lambda c: canonical_round(c.get("round_name")) ==
             canonical_round(source.get("source_round"))),
            ("exact_surface",
             lambda c: norm(c.get("surface")) == norm(raw.get("surface"))),
            ("best_of",
             lambda c: not str(raw.get("best_of") or "")
             or str(c.get("best_of")) in (
                 str(raw.get("best_of")), str(raw.get("best_of")) + ".0")),
        )
        if not candidates:
            count["context_rejected_no_canonical_pair"] += 1
        for stage, predicate in steps:
            if not candidates:
                break
            candidates = [c for c in candidates if predicate(c)]
            if not candidates:
                count["context_rejected_" + stage] += 1
                break
        if not candidates:
            count["context_rejected_no_full_match"] += 1
        if len(candidates) == 1:
            c = candidates[0]
            count["unique_full_metadata_candidates_review_only"] += 1
            core_stat_review = compare_core_service_cells(raw, c, wid, lid)
            rates_review = compare_derived_rates(raw, c, wid, lid, core_stat_review)
            possible.append({
                "source_namespace": source["source_namespace"],
                "source_native_event_key": native,
                "candidate_canonical_match_id": c["match_id"],
                "source_winner_id": sid_w,
                "source_loser_id": sid_l,
                "current_canonical_winner_id": wid,
                "context": "both_ids_winner_tournament_round_surface_week_best_of",
                "independent_event_id_attested": False,
                "score_attested": False,
                "candidate_new_null_fields": None,
                "core_serve_cells_review_only": core_stat_review,
                "derived_rate_cells_review_only": rates_review,
                "import_ready": False, "write_authorized": False,
            })
        elif len(candidates) > 1:
            count["ambiguous_canonical_event_candidates"] += 1
        else:
            count["no_full_metadata_match"] += 1
    # A canonical event must never be privately proposed twice.
    owner_count = Counter(row["candidate_canonical_match_id"] for row in possible)
    if any(n > 1 for n in owner_count.values()):
        count["ambiguous_multiple_sources_same_canonical_event"] = sum(
            n for n in owner_count.values() if n > 1)
        possible = [row for row in possible if
                    owner_count[row["candidate_canonical_match_id"]] == 1]
    # Aggregate after duplicate canonical-target quarantine, never before.
    for candidate in possible:
        count.update(candidate["core_serve_cells_review_only"])
        count.update(candidate["derived_rate_cells_review_only"])
    return possible, dict(count)


def run(gaps: Path, gaps_sha: str, legacy: Path, legacy_sha: str,
        cc0: Path, cc0_sha: str, observations: Path, observations_sha: str,
        history_dir: Path, out: Path):
    for p, sha in ((gaps, gaps_sha), (legacy, legacy_sha),
                   (cc0, cc0_sha), (observations, observations_sha)):
        sha_file(p, sha)
    matches, partition_shas = canonical_rows(history_dir)
    linked, count = valid_candidate_edges(
        read_jsonl(gaps), read_jsonl(legacy), read_jsonl(cc0), matches)
    candidates, source_count = score_event_candidates(
        read_jsonl(observations), matches, linked)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "current-cdb-event-review-private.jsonl"
    with target.open("w", encoding="utf-8") as f:
        for item in candidates:
            f.write(json.dumps(item, sort_keys=True, allow_nan=False) + "\n")
    report = {
        "schema": 1, "status": "READ_ONLY_CURRENT_CDB_SOURCE_EVENT_REVIEW",
        "canonical_years": list(YEAR_RANGE),
        "canonical_year_partition_sha256": partition_shas,
        "pinned_inputs_sha256": {
            "gaps": gaps_sha, "legacy": legacy_sha,
            "cc0": cc0_sha, "observations": observations_sha},
        "player_counts": count, "source_counts": source_count,
        "candidate_event_rows": len(candidates),
        "private_event_review_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
        "native_event_identity_verified": False,
        "score_corroborated": False,
        "ready_for_cdb_write": 0,
        "canonical_mutated": False,
        "provider_api_requests": 0, "model_trained": False,
        "policy": "Metadata-only candidate; no source event ID, score, or NULL proof",
    }
    (out / "report.json").write_text(
        json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n")
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    for name in ("gaps", "legacy", "cc0", "observations"):
        ap.add_argument(f"--{name}", type=Path, required=True)
        ap.add_argument(f"--{name}-sha256", required=True)
    ap.add_argument("--history-dir", type=Path, required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    report = run(args.gaps, args.gaps_sha256, args.legacy, args.legacy_sha256,
                 args.cc0, args.cc0_sha256, args.observations,
                 args.observations_sha256, args.history_dir, args.out)
    print(json.dumps({
        "status": report["status"], "players": report["player_counts"],
        "source": report["source_counts"], "review_only_events": report["candidate_event_rows"],
        "ready_for_cdb_write": 0, "provider_api_requests": 0,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
