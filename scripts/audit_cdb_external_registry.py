"""Independent official tennis-ID corroboration for CDB player crosswalk.

The already-published CC0 Wikidata registry is fetched by repository blob SHA.
This task is read-only and deliberately does not infer identity from rankings.
"""
from __future__ import annotations
import base64
from collections import Counter, defaultdict
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from tbt.data.player_identity import normalize_player_name

REPO = "BackstageTalks/tbt-data"
SOURCE = "research/player_identity/wikidata-tennis-identity.jsonl.gz"
DIRECTORY = Path("/tmp/blinq-comparator-readonly-audit/comparator-players.json")
ALPHANUMERIC_ATP = re.compile(r"^hist-js:atp:([A-Z][A-Z0-9]{3})$", re.I)


def gh_json(url):
    return json.loads(subprocess.check_output(["gh", "api", url], text=True, timeout=50))


def registry():
    info = gh_json(f"repos/{REPO}/contents/{SOURCE}")
    blob_sha = info.get("sha")
    if not re.fullmatch("[0-9a-f]{40}", str(blob_sha)):
        raise RuntimeError("Invalid registry blob SHA")
    blob = gh_json(f"repos/{REPO}/git/blobs/{blob_sha}")
    if blob.get("encoding") != "base64":
        raise RuntimeError("Unexpected Wikidata registry encoding")
    compressed = base64.b64decode(blob["content"])
    rows = [
        json.loads(line)
        for line in gzip.decompress(compressed).decode("utf-8").splitlines()
        if line.strip()
    ]
    if len(rows) < 1000 or any(x.get("license") != "CC0-1.0" for x in rows):
        raise RuntimeError("Incomplete or invalid registry")
    return rows, {"git_blob_sha": blob_sha, "sha256": sha256(compressed).hexdigest(), "rows": len(rows)}


def audit(directory, registry_rows):
    by_external = defaultdict(list)
    by_name = defaultdict(list)
    for row in registry_rows:
        for code in row.get("atp_ids") or []:
            by_external[("atp", str(code).lower())].append(row)
        for code in row.get("wta_ids") or []:
            by_external[("wta", str(code).lower())].append(row)
        for tour in ("atp", "wta"):
            if row.get(tour + "_ids"):
                by_name[(tour, normalize_player_name(row.get("label")))].append(row)

    by_provider_name = defaultdict(list)
    for row in directory["players"]:
        tour = str(row.get("tour") or "").lower()
        name = normalize_player_name(row.get("name"))
        if tour in {"atp", "wta"} and name and not str(row.get("player_id") or "").startswith("hist-js:"):
            by_provider_name[tour, name].append(row)

    counts = Counter()
    approved, quarantined = [], []
    for row in directory["players"]:
        if str(row.get("tour") or "").lower() != "atp":
            continue
        ident = str(row.get("player_id") or "")
        match = ALPHANUMERIC_ATP.fullmatch(ident)
        if not match:
            continue
        counts["historical_atp_code_rows"] += 1
        profiles = by_external.get(("atp", match.group(1).lower()), [])
        if len(profiles) != 1:
            counts["registry_code_missing_or_ambiguous"] += 1
            continue
        profile = profiles[0]
        name = normalize_player_name(profile.get("label"))
        if normalize_player_name(row.get("name")) != name or len(by_name[("atp", name)]) != 1:
            counts["registry_name_mismatch"] += 1
            continue
        owners = by_provider_name.get(("atp", name), [])
        if len(owners) != 1:
            counts["provider_not_unique"] += 1
            continue
        owner = owners[0]
        if str(owner.get("player_id")) == ident:
            continue
        counts["official_code_unique_provider_name"] += 1
        proposal = {
            "tour": "atp",
            "from_id": ident,
            "to_id": str(owner["player_id"]),
            "name": owner.get("name"),
            "wikidata_qid": profile.get("wikidata_qid"),
            "verified_atp_tour_id": match.group(1).upper(),
            "birth_dates": profile.get("birth_dates") or [],
            "basis": "Wikidata official ATP ID and unique canonical full spelling",
            "state": "identity_evidence_candidate_not_written",
        }
        approved.append(proposal)
    return {"counts": dict(counts), "candidates": approved[:100], "total_candidates": len(approved)}


def main():
    if not DIRECTORY.is_file():
        raise SystemExit("Verified full comparator directory is required")
    directory_raw = DIRECTORY.read_bytes()
    source, evidence = registry()
    report = audit(json.loads(directory_raw), source)
    report["source"] = evidence
    report["directory_sha256"] = sha256(directory_raw).hexdigest()
    print("CDB_ATP_ID_REGISTRY_CROSSWALK " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
