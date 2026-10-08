"""Read-only identity audit of comparator search candidates from the private verified release.

Do not consolidate canonical IDs by name. This shows raw evidence for deciding
whether a UI group is merely a homonym or could represent fragmented identity.
"""
import gzip
import json
import sys
from pathlib import Path
from release_store import ReleaseStore


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"api"))
    from tbt.data.player_identity import normalize_player_name
    cache = Path("/tmp/blinq-comparator-identity-check")
    store = ReleaseStore("BackstageTalks/tbt-data", "tbt-predictions-v1", cache)
    store.download(extra_names=("comparator.json.gz",),required_names=("comparator.json.gz",),require_bundle_manifest=True)
    with gzip.open(cache/"comparator.json.gz","rt",encoding="utf-8") as stream:
        source=json.load(stream)
    rows=source["players"]
    for surname in ("norrie","svrcina"):
        group=[]
        for p in rows:
            names=[p.get("name") or ""]+(p.get("aliases") or [])
            normalized=[normalize_player_name(v) for v in names]
            if any(surname in name.split() for name in normalized) and p.get("tour")=="atp":
                group.append({
                    "id":p.get("player_id"),"name":p.get("name"),"aliases":(p.get("aliases") or [])[:6],
                    "matches_seen":p.get("matches_seen"),"last_seen":p.get("last_seen"),
                    "rank":p.get("rank"),
                })
        group.sort(key=lambda x:(-int(x["matches_seen"] or 0),str(x["name"])))
        print("IDENTITY_AUDIT",surname,json.dumps(group[:25],ensure_ascii=False),flush=True)
        print("IDENTITY_GROUP_COUNTS",surname,len(group),flush=True)
    # Existing canonical IDs and evidence are read-only in this step.


if __name__=="__main__":
    main()
