#!/usr/bin/env python3
"""Read-only selected-only, same-N market-anchored ranking replay.

This is NOT a prospective or full-slate proof. TOP-like and PRIME-like are
heuristic proxies; model/market features may have been selected with these
same outcomes. Use mixed timezone parser to avoid false missing timestamps.
Usage: python scripts/candidate_replay_report.py results.csv
"""
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "api"))
from tbt.services.market_anchored_rank import compute_rank_probability


def load(path):
    v = pd.read_csv(path, sep=";", encoding="utf-8-sig", low_memory=False)
    required = ["Trh", "Výsledok", "Model_pravdepodobnosť_%", "Kurz",
                "Event_ID", "Dátum_zápasu",
                "src_publikácia.issued_snapshot.betting.fair_implied_probability",
                "src_publikácia.issued_snapshot.betting.captured_at"]
    missing = [c for c in required if c not in v.columns]
    if missing:
        raise ValueError("Missing evidence columns: " + ", ".join(missing))
    m = v[(v.Trh == "match_winner") & v.Výsledok.isin(["win", "loss"])].copy()
    m["y"] = (m.Výsledok == "win").astype(int)
    m["p"] = pd.to_numeric(m["Model_pravdepodobnosť_%"], errors="coerce") / 100
    m["odds"] = pd.to_numeric(m["Kurz"], errors="coerce")
    f = "src_publikácia.issued_snapshot.betting.fair_implied_probability"
    c = "src_publikácia.issued_snapshot.betting.captured_at"
    m["fair"] = pd.to_numeric(m[f], errors="coerce")
    # Mixed ISO precision with timezone offsets: default pandas parser can
    # silently lose 296 genuine pre-start records (945 -> 649).
    m["captured"] = pd.to_datetime(m[c], utc=True, errors="coerce", format="mixed")
    m["start"] = pd.to_datetime(m["Dátum_zápasu"], utc=True, errors="coerce",
                                format="mixed")
    m["day"] = m.start.dt.date
    m = m.sort_values(["p", "Event_ID"], ascending=[False, True])
    m = m.drop_duplicates("Event_ID")
    m = m[m["p"].gt(0) & m["p"].lt(1) & m["start"].notna()].copy()
    ranks = []
    for _, r in m.iterrows():
        card = {"probability": r.p,
                "scheduled_at": r.start.isoformat() if pd.notna(r.start) else None,
                "betting": {
                    "captured_at": r.captured.isoformat()
                                   if pd.notna(r.captured) else None,
                    "fair_implied_probability": None if pd.isna(r.fair) else r.fair}}
        ranks.append(compute_rank_probability(card))
    m["rank_p"] = [x for x, _ in ranks]
    m["rank_src"] = [src for _, src in ranks]
    return m


def pick(df, key, n):
    return df.sort_values([key, "Event_ID"], ascending=[False, True]).groupby("day").head(n)


def boot(champ, cand, days, B=4000, seed=0):
    rng = np.random.default_rng(seed)
    a = champ.groupby("day").y.agg(["sum", "size"]).reindex(days).fillna(0)
    b = cand.groupby("day").y.agg(["sum", "size"]).reindex(days).fillna(0)
    result = []
    for _ in range(B):
        idx = rng.integers(0, len(days), len(days))
        result.append(b["sum"].values[idx].sum() / b["size"].values[idx].sum()
                      - a["sum"].values[idx].sum() / a["size"].values[idx].sum())
    return float(np.mean(result)), *[float(x) for x in np.percentile(result, [2.5, 97.5])]


def evaluate(path):
    m = load(path)
    print(f"tips {len(m)} | days {m.day.nunique()} | with prestart fair "
          f"{(m.rank_src == 'market_anchored').sum()} | fallback "
          f"{(m.rank_src != 'market_anchored').sum()}")
    results = []
    for name, pool, n in [
        ("TOP-like (p>=.60, odds>=1.50, top3/day)",
         m[(m.p >= .60) & (m.odds >= 1.50)], 3),
        ("PRIME-like (p>=.68, odds<1.50, top10/day)",
         m[(m.p >= .68) & (m.odds < 1.50)], 10),
    ]:
        if pool.empty:
            print(name, "NO POOL")
            results.append(False)
            continue
        champ, cand = pick(pool, "p", n), pick(pool, "rank_p", n)
        days = sorted(pool.day.unique())
        delta, lo, hi = boot(champ, cand, days)
        same_n = champ.groupby("day").size().equals(cand.groupby("day").size())
        overlap = len(set(champ.Event_ID) & set(cand.Event_ID)) / max(len(champ), 1)
        print(f"\n{name}\n  champion {len(champ)} hit {champ.y.mean():.3f} | "
              f"candidate {len(cand)} hit {cand.y.mean():.3f} | "
              f"diff {delta*100:+.1f} pp 95% day-CI [{lo*100:+.1f}, {hi*100:+.1f}]"
              f" | overlap {overlap:.2f} | same N/day {same_n} | days {len(days)}")
        results.append(lo*100 > -1.0 and same_n)
    success = len(results) == 2 and all(results)
    print("\nRETROSPECTIVE NON-INFERIORITY GATE:", "PASS" if success else "FAIL")
    return success


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("Usage: candidate_replay_report.py <results.csv>")
    evaluate(Path(sys.argv[1]))
