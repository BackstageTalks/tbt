"""Build fail-closed BlinQ -> Sackmann player identity crosswalk."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.player_identity import (
    build_canonical_players,
    build_crosswalk,
    load_profiles,
    load_sackmann_players,
)


def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--history-dir",required=True)
    ap.add_argument("--tour",default="wta")
    ap.add_argument("--profiles",action="append",default=[])
    ap.add_argument("--sackmann-players",required=True)
    ap.add_argument("--out",required=True)
    ap.add_argument("--report",required=True)
    args=ap.parse_args()

    matches,safety=sanitize_history_identities(load_partitions(Path(args.history_dir)))
    if safety.get("quarantined_rows"):
        raise SystemExit("Canonical identity quarantine is non-empty")
    by_tour_id={}
    by_id={}
    for profile_path in args.profiles:
        tour_map,id_map=load_profiles(profile_path)
        by_tour_id.update(tour_map)
        by_id.update(id_map)
    canonical=build_canonical_players(
        matches,
        tour=args.tour,
        profile_by_tour_id=by_tour_id,
        profile_by_id=by_id,
    )
    sackmann=load_sackmann_players(args.sackmann_players)
    rows,report=build_crosswalk(canonical,sackmann)
    report["tour"]=args.tour.lower()
    report["profile_sources"]=list(args.profiles or [])
    report["canonical_identity_safety"]=safety

    out=Path(args.out); out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps({"schema":1,"players":rows},ensure_ascii=False,indent=2),encoding="utf-8")
    rp=Path(args.report); rp.parent.mkdir(parents=True,exist_ok=True)
    rp.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2))


if __name__=="__main__":
    main()
