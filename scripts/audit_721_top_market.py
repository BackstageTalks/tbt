"""Exact 7.2.1 TOP market observation on real issued pre-match offers.

Read-only. Uses the immutable evaluated candidate identity, signed source
publication evidence, and a real pre-issuance shadow model pair. Never infers
unissued selections or backfills unknown odds; reports INSUFFICIENT until truly
forward 7.2.1 captures have settled.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path

from audit_711_top_value_shadow import evaluate
from audit_top_reliability import issued_snapshot, number, timestamp

MIN_MATCHED_TOP = 100
MIN_PER_TOUR = 30


def exact_issued_top(ledger):
    verified = []
    reasons = Counter()
    for row in ledger:
        if not isinstance(row, dict):
            continue
        clone = {**row, "market_publications": []}
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or pub.get("section") != "top_daily":
                continue
            # No late/current/closing snapshots. Require confirmed issuer proof
            # and actual TWO-WAY market quote before the original issuance.
            snap = issued_snapshot(pub)
            if not snap or snap.get("source") != "pre_deploy_feed_confirmed":
                reasons["no_exact_prematch_issuance"] += 1
                continue
            quote = timestamp(snap.get("market_captured_at"))
            issued = timestamp(pub.get("issued_at"))
            scheduled = timestamp(row.get("scheduled_at"))
            if not quote or not issued or not scheduled or not quote <= issued < scheduled:
                reasons["missing_quote_time_or_late"] += 1
                continue
            market = snap.get("two_way_match_winner") or {}
            players = row.get("player1") or {}, row.get("player2") or {}
            pick = str(pub.get("selection_id") or "")
            idx = next((i for i, p in enumerate(players) if
                        isinstance(p, dict) and str(p.get("id") or "") == pick), None)
            odds = number(pub.get("odds"))
            quote_odds = number(market.get("player1_odds" if idx == 0 else "player2_odds")) if idx is not None else None
            if (odds is None or quote_odds is None or odds < 1.50
                    or not math.isclose(odds, quote_odds, abs_tol=1e-4, rel_tol=0)):
                reasons["unverified_selected_price"] += 1
                continue
            clone["market_publications"].append(pub)
        if clone["market_publications"]:
            verified.append(clone)
    return verified, dict(reasons)


def evaluate_721(ledger, shadow, evidence, *, now=None):
    now = now or datetime.now(timezone.utc)
    if not isinstance(evidence, dict) or evidence.get("status") != "EVALUATED_NOT_DEPLOYED":
        raise ValueError("Verified independently evaluated frozen candidate required")
    if (evidence.get("candidate_remote_readback_verified") is not True
            or evidence.get("backup_readback_verified") is not True
            or evidence.get("champion_restore_verified") is not True):
        raise ValueError("Candidate immutable release evidence missing")
    champion, candidate = evidence.get("champion_version"), evidence.get("candidate_version")
    if (not isinstance(candidate, str) or not candidate.startswith("v7.2.1-")
            or not isinstance(champion, str) or not champion):
        raise ValueError("Exact v7.2.1/champion model versions required")
    frozen, exclusions = exact_issued_top(ledger)
    result = evaluate(
        frozen, shadow, cutoff=now, champion=champion, candidate=candidate,
        sections={"top_daily"},
    )
    matched = result["matched_unique"]
    tours = result["matched_by_tour"]
    eligible_for_review = (matched >= MIN_MATCHED_TOP and
                           all(tours.get(t, 0) >= MIN_PER_TOUR for t in ("atp", "wta")))
    result.update({
        "schema": 2,
        "model_pair": {"champion": champion, "candidate": candidate},
        "candidate_release_tag": evidence["candidate_release_tag"],
        "candidate_sha256": evidence["candidate_sha256"],
        "quote_provenance_exclusions": exclusions,
        "review_gate": {
            "ready_for_independent_market_review": eligible_for_review,
            "minimum_matched_top": MIN_MATCHED_TOP, "minimum_per_tour": MIN_PER_TOUR,
            "not_a_production_promotion": True,
        },
        "market_scope": "Published >=1.50 TOP only; strict real two-way odds at issuance",
        "limits": result["limits"] + [
            "Realized ROI is from unchanged published picks, not reselected 7.2.1 picks.",
            "Even sufficient matched offers do not authorize deployment.",
        ],
        "provider_requests": 0, "production_mutated": False, "model_promoted": False,
    })
    return result


def main():
    import argparse
    from release_store import ReleaseStore
    from publish_model_calibration_status import _json_content
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-repository", default="BackstageTalks/tbt-data")
    ap.add_argument("--out", default=".cache/tbt/model-shadow-audit/721-top-market.json")
    args = ap.parse_args()
    root = Path(args.out).parent
    evidence = _json_content(
        args.data_repository, "audit/model-frozen-candidate-latest.json")
    rows = {}
    source_sha = {}
    for tag, name in (("tbt-predictions-v1", "ledger.json"),
                      ("tbt-model-shadow-v1", "shadow_ledger.json")):
        store = ReleaseStore(args.data_repository, tag, root / tag)
        store.download(required_names=(name,), require_bundle_manifest=True)
        raw = (store.directory / name).read_bytes()
        rows[name] = json.loads(raw)
        source_sha[name] = sha256(raw).hexdigest()
    report = evaluate_721(rows["ledger.json"], rows["shadow_ledger.json"], evidence)
    report["source_sha256"] = source_sha
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps({
        "status": report["status"], "matched_top": report["matched_unique"],
        "review_ready": report["review_gate"]["ready_for_independent_market_review"],
        "provider_requests": 0, "production_mutated": False,
    }))


if __name__ == "__main__":
    main()
