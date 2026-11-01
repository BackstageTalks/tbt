#!/usr/bin/env python3
"""SHA-bound read-only ATP 2025 Flashscore→current CDB research inventory.

Native Flashscore event ID and existing independent score/stat corroboration are
NOT a cross-provider native event + both-player identity witness. The report
never marks any row import_ready and never invokes a CDB writer.
"""
from __future__ import annotations

import argparse
import csv
from collections import Counter, defaultdict
import gzip
import hashlib
import json
from pathlib import Path
from datetime import datetime, timezone
import math
import re

SOURCE_SHA = "958cd93216075165895b5764d63499193a91993bb30dc00822f262713f7b31e1"
INDEX_SHA = "328f9c36c0f4021c745ca7119ea904a4ae7cadb66cee17cc63f2ca6f5774a952"
SCORE = re.compile(r"^(\d{1,2})-(\d{1,2})(?:\(\d{1,2}\))?$")
TARGETS = ("aces", "double_faults", "first_serve_win", "second_serve_win",
           "service_points_won", "return_points_won", "break_point_serve_win",
           "break_point_return_win")


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def dt(value):
    try:
        t = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return t.astimezone(timezone.utc).replace(microsecond=0) if t.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def counts(row):
    from cdb_uploaded_2025_source_stage import counts_quality, rates, game_score_quality, exact_time
    if game_score_quality(row.get("score"), row.get("best_of")) != "valid" or exact_time(row) is None:
        return None
    state, cnt = counts_quality(row)
    return rates(cnt) if state == "valid" else None


def counts_quality_gate(row):
    from cdb_uploaded_2025_source_stage import counts_quality, game_score_quality, exact_time
    if game_score_quality(row.get("score"), row.get("best_of")) != "valid" or exact_time(row) is None:
        return False
    return counts_quality(row)[0] == "valid" and all(
        row.get(k) for k in ("round", "surface", "tourney_name")
    )


def score_sets(score):
    result = []
    for s in str(score or "").split():
        m = SCORE.fullmatch(s)
        if not m:
            return None
        a, b = int(m[1]), int(m[2])
        high, low = max(a, b), min(a, b)
        if not ((high == 6 and low <= 4) or (high == 7 and low in (5, 6))
                or (high > 7 and high - low == 2)):
            return None
        result.append((a, b))
    return result if result else None


def numeric_stats(obj):
    if not isinstance(obj, dict):
        return None
    if "stats_json" in obj:
        payload = obj.get("stats_json")
        try:
            obj = json.loads(payload) if isinstance(payload, str) else payload
        except (ValueError, TypeError):
            return None
    return obj if isinstance(obj, dict) else None


def verify_row(source, indexes, canonical):
    """Classify one row conservatively; even the strongest outcome is research-only."""
    from link_uploaded_flashscore_verified import short_matches, norm

    ix = indexes.get(source["match_id"], ())
    if not ix:
        return "flashscore_event_index_absent", 0
    if len(ix) != 1:
        return "flashscore_event_id_collision", 0
    index = ix[0]
    mid = str(index.get("canonical_match_id") or "")
    if not mid:
        return "index_without_canonical_match_id", 0
    link = index.get("link")
    if not isinstance(link, dict) or link.get("accepted") is not True or link.get("orientation") not in ("direct", "swapped"):
        return "index_has_only_unverified_metadata", 0
    m = canonical.get(mid)
    if m is None:
        return "cdb_match_id_absent", 0
    if str(index.get("tour") or "").lower() != "atp" or str(m.get("tour") or "").lower() != "atp":
        return "tour_mismatch", 0
    a, b, c = dt(source.get("start_time_utc")), dt(index.get("start_utc")), dt(m.get("scheduled_at"))
    if not a or a != b or a != c:
        return "exact_utc_disagreement", 0
    if str(m.get("status") or "").lower() not in ("finished", "completed", "ended"):
        return "cdb_match_not_finished", 0
    x, y = norm(index.get("player1_source")), norm(index.get("player2_source"))
    sw, sl = norm(source.get("winner_name")), norm(source.get("loser_name"))
    if not sw or not sl or {x, y} != {sw, sl} or sw == sl:
        return "index_player_side_disagreement", 0
    winner_first = x == sw
    winner_p1 = winner_first if link["orientation"] == "direct" else not winner_first
    p1, p2 = m.get("player1_id"), m.get("player2_id")
    if not p1 or not p2 or p1 == p2:
        return "canonical_player_ids_invalid", 0
    win_id = p1 if winner_p1 else p2
    if str(m.get("winner_id")) != str(win_id):
        return "canonical_winner_conflict", 0
    wn = m.get("player1_name") if winner_p1 else m.get("player2_name")
    ln = m.get("player2_name") if winner_p1 else m.get("player1_name")
    if not short_matches(wn, source.get("winner_name")) or not short_matches(ln, source.get("loser_name")):
        return "canonical_player_names_disagree", 0
    if str(m.get("surface") or "").lower() != str(source.get("surface") or "").lower():
        return "surface_conflict", 0
    vals = score_sets(source.get("score"))
    if not vals:
        return "source_set_score_not_provable", 0
    best = m.get("best_of")
    if best is not None and not (isinstance(best, float) and math.isnan(best)) and str(int(best)) != str(source.get("best_of")):
        return "match_format_conflict", 0
    existing = numeric_stats(m)
    if existing is None:
        return "canonical_stats_malformed", 0
    for idx, (w, l) in enumerate(vals, 1):
        for side, games in (("p1", w if winner_p1 else l),
                            ("p2", l if winner_p1 else w)):
            v = existing.get(f"{side}_set{idx}_games")
            if v is None or not isinstance(v, (int, float)) or isinstance(v, bool) or float(v) != games:
                return "canonical_full_set_score_absent_or_conflict", 0
    derived = counts(source)
    if derived is None:
        return "source_invalid_serve_arithmetic", 0
    mapped = {}
    for role, values in (("w", derived["w"]), ("l", derived["l"])):
        pref = "p1" if (role == "w") == winner_p1 else "p2"
        for k, v in values.items():
            if k not in TARGETS or not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v):
                return "unapproved_or_invalid_stat", 0
            mapped[f"{pref}_{k}"] = v
    for k in ("p1_aces", "p2_aces", "p1_double_faults", "p2_double_faults"):
        v = existing.get(k)
        if v is None or isinstance(v, bool) or not isinstance(v, (int, float)) or float(v) != float(mapped.get(k, float("nan"))):
            return "four_original_stat_counts_absent_or_disagree", 0
    for k, v in mapped.items():
        old = existing.get(k)
        if old is not None and (not isinstance(old, (int, float)) or isinstance(old, bool) or abs(float(old) - float(v)) > 1e-6):
            return "other_cdb_stat_conflict", 0
    return "research_corrob_only_missing_independent_id_witness", sum(
        existing.get(k) is None for k in mapped
    )


def run(source_path, index_path, history_dir, out_path):
    import pandas as pd
    source_path, index_path, history_dir, out_path = map(
        Path, (source_path, index_path, history_dir, out_path)
    )
    if sha(source_path) != SOURCE_SHA:
        raise ValueError("Source CSV immutable SHA mismatch")
    if sha(index_path) != INDEX_SHA:
        raise ValueError("Index immutable SHA mismatch")
    bundle = json.loads((history_dir / "_tbt_bundle_manifest.json").read_text())["files"]
    manifest = json.loads((history_dir / "history_manifest.json").read_text())["years"]
    checked = {}
    for year in (2024, 2025):
        fname = f"history-{year}.parquet"
        file = history_dir / fname
        digest = sha(file)
        if bundle[fname]["sha256"] != digest or manifest[str(year)]["sha256"] != digest:
            raise ValueError("Current canonical CDB partition SHA mismatch")
        checked[fname] = digest

    seen = set()
    summary = Counter()
    sources = []
    with source_path.open(encoding="utf-8-sig", newline="") as fh:
        for row in csv.DictReader(fh):
            summary["raw"] += 1
            eid = row.get("match_id") or ""
            if not eid or eid in seen:
                raise ValueError("Duplicate source event ID")
            seen.add(eid)
            if counts_quality_gate(row):
                sources.append(row)
            else:
                summary["source_quality_review"] += 1

    idx = defaultdict(list)
    with gzip.open(index_path, "rt", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            item = json.loads(line)
            eid = str(item.get("event_id") or "")
            if eid in seen:
                idx[eid].append(item)

    cols = ["match_id", "tour", "scheduled_at", "player1_id", "player1_name",
            "player2_id", "player2_name", "winner_id", "status", "surface",
            "tournament", "best_of", "stats_json"]
    target_ids = {
        str(item.get("canonical_match_id"))
        for rows in idx.values()
        for item in rows if item.get("canonical_match_id")
    }
    canon = {}
    all_canonical = []
    for year in (2024, 2025):
        frame = pd.read_parquet(history_dir / f"history-{year}.parquet", columns=cols)
        for values in frame.itertuples(index=False, name=None):
            item = dict(zip(cols, values))
            all_canonical.append(item)
            mid = str(item["match_id"])
            if mid in target_ids:
                if mid in canon:
                    raise ValueError("Duplicate canonical match ID")
                canon[mid] = item

    potential, targets = 0, Counter()
    for src in sources:
        status, missing = verify_row(src, idx, canon)
        summary[status] += 1
        if status == "research_corrob_only_missing_independent_id_witness":
            potential += missing
            if len(idx[src["match_id"]]) == 1:
                targets[str(idx[src["match_id"]][0]["canonical_match_id"])] += 1
    if any(c > 1 for c in targets.values()):
        raise ValueError("Candidate identity bijection collision")
    summary["source_only_passed_quality"] = len(sources)
    summary["eligible_new_cells_written"] = 0
    from audit_atp2025_metadata_candidates import review as metadata_review
    metadata = metadata_review(sources, all_canonical)
    assert metadata["canonical_links_authorized"] == metadata["cdb_writes"] == 0
    report = {
        "schema": "BLINQ_ATP2025_FLASH_NATIVE_CDB_RESEARCH_RECHECK_V1",
        "state": "READ_ONLY_NO_INDEPENDENT_CROSS_PROVIDER_EVENT_AND_TWO_PLAYER_WITNESS",
        "source_sha256": SOURCE_SHA,
        "flashscore_index_sha256": INDEX_SHA,
        "cdb_partition_sha256s": checked,
        "counts": dict(sorted(summary.items())),
        "research_null_cells_not_authorized": potential,
        "metadata_research": metadata,
        "verified_links_authorized": 0,
        "import_ready": False,
        "writer_invoked": False,
        "canonical_writes": 0,
        "api_requests": 0,
        "require": "Official primary event and both participant IDs bridge across Flashscore and CDB; fresh NULL-only CAS, existing writer and independent read-back",
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        raise ValueError("Refuse overwrite existing report")
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--source-csv", type=Path, required=True)
    p.add_argument("--flashscore-index", type=Path, required=True)
    p.add_argument("--history-dir", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    x = p.parse_args()
    print(json.dumps(run(x.source_csv, x.flashscore_index, x.history_dir, x.out), sort_keys=True))


if __name__ == "__main__":
    main()
