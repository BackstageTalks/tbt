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

    by_day = defaultdict(list)
    for m in matches:
        by_day[(str(m.tour or "").lower(), m.scheduled_at.date())].append(m)

    counts, staged, review, quarantine = Counter(), [], [], []
    seen_source_ids = set()
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
                candidates = {}
                for delta in (-1, 0, 1):
                    for m in by_day.get((source.tour, source.event_date + timedelta(days=delta)), []):
                        candidates[str(m.match_id)] = m
                scored = []
                for m in candidates.values():
                    linked = candidate_link(
                        source, canonical_tour=m.tour, canonical_date=m.scheduled_at.date(),
                        canonical_player1=m.player1_name, canonical_player2=m.player2_name,
                        canonical_winner=_winner_name(m), canonical_tournament=m.tournament,
                        canonical_surface=m.surface, canonical_round=m.round_name,
                    )
                    if linked.get("score", -100) > -100:
                        scored.append((int(linked["score"]), bool(linked["accepted"]), m, linked))
                scored.sort(key=lambda x: x[0], reverse=True)
                if not scored:
                    counts["unmatched"] += 1; continue
                top_score = scored[0][0]; top = [x for x in scored if x[0] == top_score]
                if len(top) != 1:
                    counts["ambiguous"] += 1
                    review.append({"source_match_id": source.source_match_id, "reason": "ambiguous",
                                   "score": top_score, "candidate_match_ids": [str(x[2].match_id) for x in top]})
                    continue
                _, accepted, m, linked = top[0]
                if not accepted:
                    counts["weak_evidence"] += 1
                    review.append({"source_match_id": source.source_match_id, "reason": "weak_evidence",
                                   "candidate_match_id": str(m.match_id), "score": linked["score"],
                                   "evidence": linked["evidence"]})
                    continue
                marker = build_market_history_marker(source=source, linked=linked,
                    source_label=args.source_label, source_file_sha256=sha)
                existing = (m.provider_payload or {}).get("_tbt_market_history")
                if existing:
                    counts["already_present"] += 1
                    quarantine.append({"match_id": str(m.match_id), "source_match_id": source.source_match_id,
                                       "reason": "existing_market_history_preserved"})
                    continue
                counts["staged_matches"] += 1
                staged.append({"schema": 1, "match_id": str(m.match_id), "canonical": _signature(m),
                    "incoming_market_history": marker,
                    "source": {"row_number": number, "source_match_id": source.source_match_id,
                               "score": linked["score"], "evidence": linked["evidence"],
                               "orientation": linked["orientation"]}, "import_ready": True})

    report = {"schema": 1, "canonical_rows": len(matches), "counts": dict(counts),
              "production_mutated": False, "api_requests": 0,
              "license": "CC BY 4.0", "source": "Valuebetennis",
              "model_feature_policy": "opening_only_candidate; closing_validation_only"}
    (out/"report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    for name, rows in (("auto_linked.jsonl", staged), ("review.jsonl", review), ("quarantine.jsonl", quarantine)):
        with (out/name).open("w", encoding="utf-8") as h:
            for row in rows: h.write(json.dumps(row, ensure_ascii=False)+"\n")
    print(json.dumps(report, indent=2, ensure_ascii=False))


if __name__ == "__main__": main()
