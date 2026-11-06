"""Pinned read-only Safonov source/selection audit. No model, CDB, API or ledger writes.

Reads current *versioned* private release assets and immutable Telegram receipts.
The monthly selector snapshots are point-in-time samples, NOT automatically
equivalent to original public issuance; report that distinction explicitly.
"""
from __future__ import annotations

import argparse
import base64
import gzip
import hashlib
import json
import math
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = "BackstageTalks/tbt-data"
TAG = "tbt-predictions-v1"
ASSETS = (
    "_tbt_bundle_manifest.json", "selection_candidates_2026-11.json.gz",
    "daily_offer_snapshot.json", "feed.json", "ledger.json",
)
TZ = ZoneInfo("Europe/Bratislava")
TARGET = "safonov"


def gh(*args: str) -> str:
    result = subprocess.run(["gh", *args], capture_output=True, text=True, check=True)
    return result.stdout


def inventory() -> dict:
    release = json.loads(gh("api", f"repos/{REPO}/releases/tags/{TAG}"))
    assets = {x["name"]: {k: x.get(k) for k in ("id", "size", "digest", "updated_at")}
              for x in release.get("assets") or []}
    missing = set(ASSETS) - set(assets)
    if missing:
        raise RuntimeError(f"Required release assets missing: {sorted(missing)}")
    return {name: assets[name] for name in ASSETS}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as reader:
        for block in iter(lambda: reader.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def download(root: Path) -> dict:
    root.mkdir(parents=True, exist_ok=True)
    before = inventory()
    for name in ASSETS:
        gh("release", "download", TAG, "--repo", REPO, "--pattern", name,
           "--dir", str(root), "--clobber")
    after = inventory()
    if before != after:
        raise RuntimeError("Release assets changed during audit; refusing mixed-source evidence")
    manifest = json.loads((root / ASSETS[0]).read_text(encoding="utf-8"))
    source = {}
    for name in ASSETS:
        path = root / name
        expected = before[name]
        if path.stat().st_size != expected["size"]:
            raise RuntimeError(f"Asset size mismatch: {name}")
        digest = sha256(path)
        if expected.get("digest") and expected["digest"] != "sha256:" + digest:
            raise RuntimeError(f"Asset release digest mismatch: {name}")
        proof = (manifest.get("files") or {}).get(name)
        if name != ASSETS[0]:
            if not isinstance(proof, dict):
                raise RuntimeError(f"Missing signed manifest entry: {name}")
            if proof.get("sha256") != digest or proof.get("bytes") != path.stat().st_size:
                raise RuntimeError(f"Manifest mismatch: {name}")
        source[name] = {**expected, "sha256": digest}
    return source


def utc(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None


def n(value):
    try:
        x = float(value)
        return x if math.isfinite(x) else None
    except (ValueError, TypeError):
        return None


def is_safonov(row):
    return any(TARGET in str((row.get(side) or {}).get("name") or "").lower()
               for side in ("player1", "player2")) or TARGET in str(row.get("pick") or row.get("selection") or "").lower()


def summarize(row, source, *, snapshot_at=None):
    bet = row.get("betting") if isinstance(row.get("betting"), dict) else {}
    market = row.get("two_way_market") if isinstance(row.get("two_way_market"), dict) else row.get("match_winner_market")
    market = market if isinstance(market, dict) else {}
    p1 = row.get("player1") or {}
    p2 = row.get("player2") or {}
    winner_id = str(row.get("winner_id") or "")
    selected_id = str(bet.get("selection_id") or row.get("selection_id") or "")
    p1id, p2id = str(p1.get("id") or ""), str(p2.get("id") or "")
    selected_side = 1 if selected_id == p1id and p1id else 2 if selected_id == p2id and p2id else None
    win_side = 1 if winner_id == p1id and p1id else 2 if winner_id == p2id and p2id else None
    price = n(bet.get("odds") or row.get("odds"))
    pair_price = n(market.get("player1_odds" if selected_side == 1 else "player2_odds")) if selected_side else None
    raw = n(bet.get("model_probability") or row.get("raw_model_probability"))
    public = n(bet.get("blinq_probability") or row.get("blinq_probability") or row.get("probability"))
    if public is not None and public > 1:
        public = public / 100
    start = utc(row.get("scheduled_at"))
    captured = utc(bet.get("captured_at") or market.get("captured_at"))
    derived = {
        "selection_matches_winner": bool(selected_id and selected_id == winner_id),
        "winner_is_max_probability": None,
        "selected_odds_match_two_way": None if not (price and pair_price) else abs(price - pair_price) < 0.0001,
        "quote_before_start": None if not (captured and start) else captured < start,
        "snapshot_before_start": None if not (snapshot_at and start) else utc(snapshot_at) < start,
        "extreme_gap_over_50pp": None if not (public and price and price > 1) else public - 1 / price > .50,
    }
    p1p, p2p = n(p1.get("probability")), n(p2.get("probability"))
    if p1p is not None and p2p is not None and win_side:
        derived["winner_is_max_probability"] = (p1p >= p2p if win_side == 1 else p2p >= p1p)
    return {
        "source": source, "event_id": str(row.get("event_id") or ""),
        "scheduled_at": row.get("scheduled_at"), "snapshot_at": snapshot_at,
        "model_version": row.get("model_version"),
        "tour": row.get("tour"), "tournament": row.get("tournament"), "surface": row.get("surface"),
        "player1": {k: p1.get(k) for k in ("id", "name", "rank", "probability")},
        "player2": {k: p2.get(k) for k in ("id", "name", "rank", "probability")},
        "winner_id": winner_id, "selection_id": selected_id, "selected_side": selected_side,
        "selected_section": row.get("selected_section"), "selection_tier": row.get("selection_tier"),
        "raw_probability": raw, "public_probability": public, "odds": price,
        "implied_probability": 1 / price if price and price > 1 else None,
        "market_pair": {k: market.get(k) for k in (
            "player1_odds", "player2_odds", "provider_id", "source", "source_id",
            "source_id_known", "raw_overround", "captured_at", "bookmaker", "provider_event_id")},
        "betting": {k: bet.get(k) for k in ("provider_id", "captured_at", "betting_day", "selection")},
        "depth": row.get("data_depth"), "stats_available": row.get("stats_available"),
        "samples": row.get("samples") or row.get("quality"),
        "checks": derived,
    }


def read_report(root: Path, pins: dict) -> dict:
    with gzip.open(root / ASSETS[1], "rt", encoding="utf-8") as reader:
        monthly = json.load(reader)
    snapshots = [s for s in (monthly.get("snapshots") or [])
                 if isinstance(s, dict) and utc(s.get("generated_at")) is not None
                 and utc(s["generated_at"]).astimezone(TZ).date().isoformat() == "2026-11-06"]
    matched = []
    cohort = Counter()
    for snap in snapshots:
        generated = snap["generated_at"]
        entries = snap.get("rows") or []
        for row in entries:
            if not isinstance(row, dict):
                continue
            pub = n(row.get("blinq_probability"))
            odds = n((row.get("betting") or {}).get("odds"))
            if row.get("selected_section") == "top_daily":
                cohort["top_snapshots_rows"] += 1
                if pub is not None and odds and odds > 1:
                    gap = pub - 1 / odds
                    if gap > .3: cohort["top_gap_over_30pp"] += 1
                    if gap > .4: cohort["top_gap_over_40pp"] += 1
                    if gap > .5: cohort["top_gap_over_50pp"] += 1
            if is_safonov(row):
                matched.append(summarize(row, "monthly_candidate", snapshot_at=generated))
        cohort["snapshots"] += 1
        cohort["candidate_rows"] += len(entries)
    feeds = {}
    events = set()
    for key, name in (("feed.json", "serving_feed"), ("daily_offer_snapshot.json", "daily_snapshot")):
        data = json.loads((root / key).read_text(encoding="utf-8"))
        rows = []
        for section in ("upcoming", "top_daily_picks", "prime_picks", "value_picks"):
            for row in data.get(section) or []:
                if not isinstance(row, dict) or not is_safonov(row):
                    continue
                rec = summarize(row, name + "." + section, snapshot_at=data.get("generated_at"))
                rows.append(rec)
                if rec["event_id"]: events.add(rec["event_id"])
        feeds[name] = {"generated_at": data.get("generated_at"),
                       "top_count": len(data.get("top_daily_picks") or []),
                       "safonov": rows}
    events |= {r["event_id"] for r in matched if r["event_id"]}
    ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
    issued = []
    for row in ledger:
        if not isinstance(row, dict) or (str(row.get("event_id") or "") not in events and not is_safonov(row)):
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict) or pub.get("market") != "match_winner":
                continue
            snap = pub.get("issued_snapshot") if isinstance(pub.get("issued_snapshot"), dict) else {}
            prepared = pub.get("prepared_snapshot") if isinstance(pub.get("prepared_snapshot"), dict) else {}
            issued.append({
                "event_id": row.get("event_id"),
                "section": pub.get("section"), "selection_id": pub.get("selection_id"),
                "odds": pub.get("odds"), "model_probability": pub.get("model_probability"),
                "captured_at": pub.get("captured_at"), "issued_at": pub.get("issued_at"),
                "publication_status": pub.get("publication_status"),
                "publication_key": pub.get("publication_key"),
                "frozen_evidence": {
                    "source": snap.get("source"), "schema": snap.get("schema"),
                    "prepared_at": snap.get("prepared_at"),
                    "confirmed_at": snap.get("confirmed_at"),
                    "market_captured_at": snap.get("market_captured_at"),
                    "feed_generated_at": snap.get("feed_generated_at"),
                    "model_version": snap.get("model_version"),
                    "model_probability": snap.get("model_probability"),
                    "blinq_probability": snap.get("blinq_probability"),
                    "odds": snap.get("odds"),
                    "provider_id": snap.get("provider_id"),
                    "players": snap.get("players"),
                    "quality": snap.get("quality"),
                    "two_way_match_winner": snap.get("two_way_match_winner"),
                },
                "prepared_snapshot_present": bool(prepared),
                "prepared_evidence": {
                    "prepared_at": prepared.get("prepared_at"),
                    "market_captured_at": prepared.get("market_captured_at"),
                    "model_version": prepared.get("model_version"),
                    "model_probability": prepared.get("model_probability"),
                    "provider_id": prepared.get("provider_id"),
                    "two_way_match_winner": prepared.get("two_way_match_winner"),
                    "players": prepared.get("players"),
                    "quality": prepared.get("quality"),
                } if prepared else None,
            })
    encoded = json.loads(gh("api", f"repos/{REPO}/contents/ops/telegram-bot-state.json?ref=telegram-bot-state"))
    sent = json.loads(base64.b64decode(encoded["content"]).decode("utf-8"))
    batch = (sent.get("attempts") or {}).get("2026-11-06:daily:0620") or {}
    top_rows = [x for x in batch.get("rows") or [] if x.get("channel") == "top"]
    return {
        "schema": 1, "status": "READ_ONLY_PINNED_EVIDENCE",
        "source_pins": pins,
        "candidate": {"cohort": dict(cohort), "safonov": matched},
        "feed": feeds, "issued_publications": issued,
        "telegram": {
            "status": batch.get("status"), "sent_at": batch.get("sent_at"),
            "message_ids": batch.get("message_ids"), "top": top_rows,
            "safonov_present": any(TARGET in str(x.get("name") or "").lower()
                                   for x in batch.get("rows") or []),
        },
        "limits": [
            "Monthly candidate rows are full point-in-time selector inputs, not exact issued bets.",
            "Current release assets can have been refreshed since original 07:26 start.",
            "No raw source provider payload or point-in-time full feature vector in selector snapshot.",
            "Site/account authorized TOP needs independent signed production member readback.",
        ],
        "provider_requests": 0, "CDB_mutated": False, "model_mutated": False,
        "production_mutated": False, "telegram_mutated": False,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--cache", default=".cache/safonov-frozen")
    args = parser.parse_args()
    root = Path(args.cache)
    pins = download(root)
    result = read_report(root, pins)
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n",
                      encoding="utf-8")
    print(json.dumps({
        "status": result["status"], "cohort": result["candidate"]["cohort"],
        "candidate_matches": len(result["candidate"]["safonov"]),
        "candidate_safonov": result["candidate"]["safonov"][:15],
        "feed_safonov": result["feed"],
        "issued_publications": result["issued_publications"][:15],
        "tg_status": result["telegram"]["status"],
        "tg_safonov": result["telegram"]["safonov_present"],
        "provider_requests": 0, "CDB_mutated": False, "production_mutated": False,
    }, ensure_ascii=False, allow_nan=False))


if __name__ == "__main__":
    main()
