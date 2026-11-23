#!/usr/bin/env python3
"""Read-only segment backtest on the canonical CDB (no writes, no API).

TOP: favourite hit-rate by opening-odds bucket and level.
VALUE: balanced matches (both opening odds 1.70-2.20); pick the player whose
prior-only rolling serve+return quality is higher by >= EDGE; report hit rate
vs break-even and ROI at opening odds. Rolling stats use ONLY earlier matches.
"""
from __future__ import annotations
import json, sys
from collections import defaultdict, deque
from pathlib import Path
import pandas as pd

H = Path(sys.argv[1]); YEARS = range(2022, 2027); N = 20; EDGE = 0.06


def lvl(x):
    x = str(x).lower()
    if "itf" in x and "women" in x: return "ITF W"
    if "itf" in x or "futures" in x: return "ITF M"
    if "challenger" in x: return "Challenger"
    if "wta 125" in x: return "WTA 125"
    if "wta" in x: return "WTA"
    if "atp" in x or "grand slam" in x or "masters" in x: return "ATP"
    return None


rows = []
for y in YEARS:
    f = pd.read_parquet(H / f"history-{y}.parquet", columns=["match_id", "scheduled_at", "player1_id", "player2_id",
        "winner_id", "tournament_level", "stats_json", "provider_context_json", "player1_rank", "player2_rank"])
    rows.append(f)
d = pd.concat(rows)
d["t"] = pd.to_datetime(d.scheduled_at, utc=True, errors="coerce")
d = d.dropna(subset=["t"]).sort_values("t")
hist = defaultdict(lambda: deque(maxlen=N))
top = defaultdict(lambda: [0, 0]); val = defaultdict(lambda: [0, 0, 0.0]); rk = defaultdict(lambda: [0, 0])
for m in d.itertuples():
    L = lvl(m.tournament_level)
    p1, p2, w = str(m.player1_id), str(m.player2_id), str(m.winner_id)
    pc = json.loads(m.provider_context_json) if isinstance(m.provider_context_json, str) else {}
    st = json.loads(m.stats_json) if isinstance(m.stats_json, str) else {}
    mh = (pc.get("_tbt_market_history") or {}).get("opening") or {}
    o1, o2 = mh.get("player1_odds"), mh.get("player2_odds")
    if L and w in (p1, p2) and o1 and o2:
        fav_p1 = o1 < o2; fo = min(o1, o2)
        b = "1.10-1.30" if fo < 1.30 else "1.30-1.50" if fo < 1.50 else "1.50-1.70" if fo < 1.70 else "1.70+"
        top[(L, b)][0] += 1; top[(L, b)][1] += (w == p1) == fav_p1
        q1 = [x for x in hist[p1]]; q2 = [x for x in hist[p2]]
        if 1.70 <= o1 <= 2.20 and 1.70 <= o2 <= 2.20 and len(q1) >= 5 and len(q2) >= 5:
            e = sum(q1) / len(q1) - sum(q2) / len(q2)
            if abs(e) >= EDGE:
                pick1 = e > 0; win = (w == p1) == pick1; odds = o1 if pick1 else o2
                v = val[L]; v[0] += 1; v[1] += win; v[2] += (odds - 1) if win else -1
            r1, r2 = m.player1_rank, m.player2_rank
            if pd.notna(r1) and pd.notna(r2) and r1 != r2:
                rk[L][0] += 1; rk[L][1] += (w == p1) == (r1 < r2)
    if "p1_service_points_won" in st and "p1_return_points_won" in st and w in (p1, p2):
        hist[p1].append(st["p1_service_points_won"] + st["p1_return_points_won"])
        hist[p2].append(st["p2_service_points_won"] + st["p2_return_points_won"])
print("TOP_TABLE")
for (L, b), (n, k) in sorted(top.items()):
    if n >= 200: print(f"TOP {L:10s} {b:10s} n={n:6d} hit={k/n*100:5.1f}%")
print("VALUE_TABLE (edge>=%.2f, balanced 1.70-2.20, opening odds)" % EDGE)
for L, (n, k, pnl) in sorted(val.items()):
    if n: print(f"VALUE {L:10s} n={n:5d} hit={k/n*100:5.1f}% roi={pnl/n*100:+5.1f}%")
print("RANK_IN_BALANCED (better-ranked wins)")
for L, (n, k) in sorted(rk.items()):
    if n: print(f"RANK {L:10s} n={n:5d} hit={k/n*100:5.1f}%")
