"""Independent identity evidence for two historized ATP player IDs.

Checks public Sackmann-style player registry and pre-existing private profile
release. No canonical edits, provider API calls, training or model activation.
"""
import csv
import hashlib
import io
import json
import subprocess
import tempfile
import urllib.request
from pathlib import Path

SOURCE_URLS = [
    "https://raw.githubusercontent.com/JeffSackmann/tennis_atp/master/atp_players.csv",
    "https://raw.githubusercontent.com/Kadantte/tennis_atp/master/atp_players.csv",
]
SOURCE_IDS = {"N771": "Cameron Norrie", "207494": "Dalibor Svrcina"}
PROVIDER_IDS = {"95935": "Cameron Norrie", "260122": "Dalibor Svrcina"}


def public_registry():
    for url in SOURCE_URLS:
        try:
            req = urllib.request.Request(url, headers={"User-Agent":"BlinQ-read-only-identity-audit"})
            with urllib.request.urlopen(req, timeout=15) as response:
                content = response.read()
            rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
            collected = {}
            for row in rows:
                identifier = str(row.get("player_id") or "").strip()
                if identifier in SOURCE_IDS:
                    collected[identifier] = {
                        key: str(value)[:100] for key, value in row.items()
                        if key in {"player_id","name_first","name_last","first_name",
                                   "last_name","dob","birth_date","ioc","country_code"}
                    }
            return {"url": url, "sha256": hashlib.sha256(content).hexdigest(),
                    "rows": collected, "complete": len(collected) == len(SOURCE_IDS)}
        except Exception as exc:
            print("PUBLIC_SOURCE_UNAVAILABLE",url,type(exc).__name__,str(exc)[:150],flush=True)
    return {"complete": False, "rows": {}, "error": "public_source_unavailable"}


def player_profiles():
    with tempfile.TemporaryDirectory(prefix="blinq-player-profiles-") as directory:
        subprocess.run([
            "gh","release","download","tbt-player-assets-v1",
            "--repo","BackstageTalks/tbt-data","--pattern",
            "player_profiles.json","--dir",directory,"--clobber",
        ],check=True,capture_output=True,text=True,timeout=90)
        path = Path(directory)/"player_profiles.json"
        raw=path.read_bytes()
        obj=json.loads(raw)
    matches=[]
    def scan(value,key="",depth=0):
        if depth>5 or len(matches)>=30:
            return
        if isinstance(value,dict):
            tokens=" ".join(str(v) for k,v in value.items() if k in (
                "id","player_id","name","full_name","first_name","last_name",
                "canonical_name","display_name","birth_date","dob",
            ))
            if any(identifier==str(value.get(k) or "") for identifier in PROVIDER_IDS for k in ("id","player_id","playerId")) or (
                "Cameron Norrie" in tokens or "Dalibor" in tokens and ("Svrcina" in tokens or "Svrčina" in tokens)
            ):
                matches.append({"lookup_key":key,"attributes":{
                    k:str(v)[:140] for k,v in value.items()
                    if k in ("id","player_id","name","full_name","first_name","last_name","canonical_name","display_name","birth_date","dob","country","country_code","nationality","atp_id")
                }})
                return
            for k,v in value.items():
                if k in PROVIDER_IDS:
                    scan(v,str(k),depth+1)
                elif isinstance(v,(dict,list)):
                    scan(v,k,depth+1)
        elif isinstance(value,list):
            for v in value:
                scan(v,key,depth+1)
    scan(obj)
    return {"sha256":hashlib.sha256(raw).hexdigest(),"bytes":len(raw),
            "matches":matches[:20],"root_type":type(obj).__name__,
            "root_keys":list(obj)[:12] if isinstance(obj,dict) else None}


def main():
    print("INDEPENDENT_ID_EVIDENCE",json.dumps(public_registry(),ensure_ascii=False),flush=True)
    print("PROVIDER_PROFILE_EVIDENCE",json.dumps(player_profiles(),ensure_ascii=False),flush=True)
    print("PROFILE_AUDIT_COMPLETE read_only=true api_requests=0",flush=True)


if __name__=="__main__":
    main()
