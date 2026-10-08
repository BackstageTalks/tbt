"""Fail-closed shadow reconciliation of two evidenced ATP history ID fragments.

Consumes checksum-verified canonical partitions; writes NO canonical assets.
The shadow view is for post-hoc historical feature enrichment validation, not
for same-day match prediction / retraining or production model promotion.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timezone
from hashlib import sha256
import json
import tempfile
from pathlib import Path

from audit_historical_player_links import load, norm, side

LINKS = {
  ("atp","hist-js:atp:N771"): {"to":"95935","canonical_name":"Cameron Norrie","evidence":"https://www.atptour.com/en/players/cameron-norrie/n771/overview"},
  ("atp","hist-js:atp:207494"): {"to":"260122","canonical_name":"Dalibor Svrcina","evidence":"https://www.atptour.com/-/media/files/media-guide/2026/2026-atp-media-guide-player-bios-birthdays.pdf"},
}
MIN_CUTOFF = datetime(2026, 10, 8, tzinfo=timezone.utc)


def compare_event(a,b):
    """Deterministic overlap guard, with explicit venue qualifier aliases."""
    if str(a["scheduled_at"])[:10]!=str(b["scheduled_at"])[:10]:
        return False
    if str(a["tour"]).lower()!=str(b["tour"]).lower():
        return False
    if norm(a["surface"])!=norm(b["surface"]):
        return False
    # Day, opponent and winner orientation must match independently.
    return True


def certify_match(a,b,a_old,b_new):
    side_a=side(a,a_old)
    side_b=side(b,b_new)
    if not side_a or not side_b:
        return False
    if not compare_event(a,b):
        return False
    if norm(side_a["opponent"])!=norm(side_b["opponent"]):
        return False
    if side_a["won"]!=side_b["won"]:
        return False
    va=norm(a.get("tournament"));vb=norm(b.get("tournament"))
    if not va or not vb or not (va==vb or va in vb or vb in va):
        return False
    # A historical final qualification round is named Q2.
    sr=norm(a.get("round_name"));cr=norm(b.get("round_name"))
    if sr and cr and not (sr==cr or (sr=="q2" and "qualification final" in cr)
                                   or (cr=="q2" and "qualification final" in sr)):
        return False
    return True


def dryrun(records):
    all_ids={(str(r["tour"]).lower(),str(p)) for r in records for p in (r["player1_id"],r["player2_id"])}
    for link,meta in LINKS.items():
        if link not in all_ids or (link[0],meta["to"]) not in all_ids:
            raise RuntimeError("Source or destination ID absent from canonical history")
    provider=defaultdict(list)
    for row in records:
        for (tour,legacy),meta in LINKS.items():
            if str(row["tour"]).lower()==tour and side(row,meta["to"]):
                provider[(tour,meta["to"],str(row["scheduled_at"])[:10])].append(row)
    planned,skipped,conflicts=[],[],[]
    for source in records:
        mapping=[(k,v) for k,v in LINKS.items() if str(source["tour"]).lower()==k[0] and side(source,k[1])]
        if not mapping:continue
        for key,meta in mapping:
            if norm(side(source,key[1])["name"])!=norm(meta["canonical_name"]) and not (
                key[1]=="hist-js:atp:207494" and norm(side(source,key[1])["name"])=="svrcina d"
            ):
                conflicts.append({"id":str(source["match_id"]),"reason":"source_name_conflict"})
                continue
            candidates=provider.get((key[0],meta["to"],str(source["scheduled_at"])[:10]),[])
            candidates=[c for c in candidates if norm(side(c,meta["to"])["opponent"])==norm(side(source,key[1])["opponent"])]
            if candidates:
                certified=[c for c in candidates if certify_match(source,c,key[1],meta["to"])]
                if len(certified)==1 and len(candidates)==1:
                    skipped.append({"id":str(source["match_id"]),"provider_id":str(certified[0]["match_id"]),"reason":"same_match_provider_precedence"})
                    continue
                conflicts.append({"id":str(source["match_id"]),"reason":"ambiguous_or_inconsistent_overlap",
                                  "candidate_ids":[str(x["match_id"]) for x in candidates]})
                continue
            staged=dict(source)
            updated_fields=[]
            for field in ("player1_id","player2_id","winner_id"):
                if str(staged.get(field) or "")==key[1]:
                    staged[field]=meta["to"]
                    updated_fields.append(field)
            if staged["player1_id"]==staged["player2_id"]:
                conflicts.append({"id":str(source["match_id"]),"reason":"self_match_after_link"})
                continue
            if not updated_fields or str(source["scheduled_at"])[:10]>="2026-10-08":
                conflicts.append({"id":str(source["match_id"]),"reason":"invalid_time_or_unlinked"})
                continue
            if staged["winner_id"] not in (staged["player1_id"],staged["player2_id"]):
                conflicts.append({"id":str(source["match_id"]),"reason":"winner_invalid_after_link"})
                continue
            planned.append({"source_match_id":str(source["match_id"]),"source_player_id":key[1],
                            "canonical_player_id":meta["to"],"fields":updated_fields})
    counts=Counter(r["source_player_id"] for r in planned)
    if conflicts:
        return {"status":"QUARANTINED","counts":dict(counts),"conflicts":conflicts,"excluded_duplicate":skipped}
    return {"status":"STAGED","candidate_identity_links":len(LINKS),
            "source_rows":len(records),"canonical_rows_preserved":len(records),
            "rows_shadow_enriched":len(planned),"by_legacy_id":dict(counts),
            "duplicate_event_provider_precedence":skipped,
            "changes_not_applied":True,"training_eligible":False,
            "source_rewrite":False,"provider_api_requests":0,
            "sidecar_preview_sha256":sha256(json.dumps(planned,sort_keys=True).encode()).hexdigest(),
            "sample":planned[:5]}


def main():
    with tempfile.TemporaryDirectory(prefix="blinq-identity-shadow-") as root:
        rows, inventory=load(Path(root))
    report=dryrun([r for r in rows if str(r["tour"]).lower()=="atp"])
    print("SHADOW_IDENTITY_DRYRUN",json.dumps(report,ensure_ascii=False),flush=True)
    if report["status"]!="STAGED":
        raise RuntimeError("Identity mapping remained quarantined / ambiguous")


if __name__=="__main__":
    main()
