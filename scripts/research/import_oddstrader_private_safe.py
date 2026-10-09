#!/usr/bin/env python3
"""Safely reconcile OddsTrader ATP 2015-2026 with CURRENT private canonical.

No provider requests, no models, no fabricated quote timestamps. Source-labeled
openers are observational historical odds; unknown-time bookmaker prices are
never labelled as opening or closing. Only exact-day, unique player+winner
matches can be used. Private immutable backup and SHA readback are required.
"""
from __future__ import annotations
import csv
import gzip
import hashlib
import json
import os
import shutil
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
from release_store import ReleaseStore

DATA_REPO = "BackstageTalks/tbt-data"
ROOT = Path(".cache/tbt/oddstrader-safe")
SOURCE = Path("private_data/data/oddstrader/atp")
BEFORE = ROOT / "before"
SHADOW = ROOT / "shadow"
STAGE = ROOT / "stage"
OUT = ROOT / "import"
RUN_ID = os.environ["GITHUB_RUN_ID"]
BACKUP = "blinq-canonical-backup-" + RUN_ID
TARGET = f"audit/oddstrader-current-canonical-{RUN_ID}.json"
ALLOWED_MARKERS = {"_tbt_market_history", "_tbt_match_winner_odds"}

def gh(*args) -> str:
    return subprocess.check_output(["gh", *map(str, args)], text=True).strip()

def hash_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()

def run(*args):
    res = subprocess.run(list(map(str, args)), stdout=subprocess.PIPE,
                         stderr=subprocess.PIPE, text=True)
    if res.returncode:
        raise RuntimeError(f"Step {args[1] if len(args)>1 else args[0]} failed: {res.stderr[-1000:]}")
    print("Completed guarded subprocess:", Path(str(args[1] if len(args)>1 else args[0])).name,
          flush=True)

def private_put(path: str, obj: dict):
    import base64
    content = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False).encode()
    body = {"message": f"audit: verified OddsTrader private canonical reconciliation {RUN_ID}",
            "content": base64.b64encode(content).decode()}
    lookup = subprocess.run(["gh", "api", f"repos/{DATA_REPO}/contents/{path}"],
                            capture_output=True, text=True)
    if lookup.returncode == 0:
        body["sha"] = json.loads(lookup.stdout)["sha"]
    elif "404" not in lookup.stderr:
        raise RuntimeError("Cannot safely discover private audit target state")
    payload = ROOT / "audit_body.json"
    payload.write_text(json.dumps(body))
    gh("api", "--method", "PUT", f"repos/{DATA_REPO}/contents/{path}",
       "--input", str(payload))

def history_asset_identities() -> dict:
    release = json.loads(gh("api", f"repos/{DATA_REPO}/releases/tags/tbt-data-v1"))
    return {a["name"]: (a["id"], a["size"], a.get("digest"))
            for a in release["assets"]
            if a["name"] == "history_manifest.json" or
            (a["name"].startswith("history-") and a["name"].endswith(".parquet"))}

def ensure_same_as_backup(proof: dict):
    expected = {n: (item["source_id"], item["bytes"], "sha256:" + item["sha256"])
                for n, item in proof["sha256"].items()}
    if history_asset_identities() != expected:
        raise RuntimeError("Canonical release diverged from sealed backup; refuse write")

def rows(directory: Path) -> int:
    manifest = json.loads((directory / "history_manifest.json").read_text())
    return sum(int(entry["rows"]) for entry in manifest["years"].values())

def source_gate() -> dict:
    assert SOURCE.is_dir()
    summary = json.loads((SOURCE / "summary.json").read_text())
    if summary.get("total_rows", 0) < 1_000_000 or summary.get("total_pages", 0) < 34_000:
        raise RuntimeError("Incomplete OddsTrader source manifest")
    checks = {}
    total = 0
    for year in range(2015, 2027):
        name = f"{year}.csv"
        path = SOURCE / name
        page_file = SOURCE / f"{year}.pages.csv"
        if not path.is_file() or not page_file.is_file():
            raise RuntimeError("Missing source CSV/page manifest: " + name)
        with page_file.open("r", encoding="utf-8-sig", newline="") as f:
            pages = list(csv.DictReader(f))
        if len(pages) != summary["years"][str(year)]["pages_ok"] or any(
            row.get("status") != "ok" for row in pages
        ):
            raise RuntimeError("Incomplete page-level acquisition evidence: " + name)
        with path.open("rb") as f:
            count = sum(part.count(b"\n") for part in iter(lambda: f.read(1 << 20), b"")) - 1
        if count != summary["years"][str(year)]["rows"]:
            raise RuntimeError(f"CSV row-count mismatch for {year}: {count}")
        total += count
        checks[name] = {"sha256": hash_file(path), "rows": count,
                        "pages_verified": len(pages), "bytes": path.stat().st_size}
    if total != summary["total_rows"]:
        raise RuntimeError(f"Source total changed: {total}")
    return {"source_rows": total, "page_count": summary["total_pages"],
            "files": checks, "private_checkout_sha":
            gh("-C", "private_data", "rev-parse", "HEAD") if False else
            subprocess.check_output(["git", "-C", "private_data", "rev-parse", "HEAD"],
                                    text=True).strip()}

def filter_linked(stage: Path):
    """Only exact-day oriented, unambiguous canonical linked matches."""
    keep = set()
    stats = Counter()
    stage_by_kind = {}
    for kind in ("opening", "fallback"):
        p = stage / f"{kind}_stage.jsonl"
        selected = []
        with p.open(encoding="utf-8") as f:
            for line in f:
                if not line.strip():
                    continue
                row = json.loads(line)
                src_date = str(row.get("source", {}).get("date", ""))
                canonical_date = str(row.get("canonical", {}).get("scheduled_date_utc", ""))
                if src_date != canonical_date:
                    stats["skipped_cross_day"] += 1
                    continue
                mid = str(row["match_id"])
                if mid in keep:
                    # Ambiguous duplicate source rows must not be promoted.
                    stats["duplicate_across_markets"] += 1
                    continue
                keep.add(mid)
                # Never create a fake close or precise quote timestamp. The
                # source explicitly labels the opener; fallback remains unknown-time.
                incoming = row.get("incoming_market_history") or row.get("incoming_market")
                if incoming.get("closing") is not None or incoming.get("quote_timestamp") is not None:
                    raise RuntimeError("Unverified quote timing present in staged record")
                selected.append(row)
        out = stage / f"{kind}_safe.jsonl"
        with out.open("w", encoding="utf-8") as f:
            for row in selected:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        stage_by_kind[kind] = out
        stats[f"{kind}_exact_day_rows"] = len(selected)

    sidecar_files = []
    for f in sorted(stage.glob("oddstrader-market-sidecar-*.jsonl.gz")):
        dest = stage / f.name.replace(".jsonl.gz", "-exact-day.jsonl.gz")
        count = 0
        with gzip.open(f, "rt", encoding="utf-8") as src, gzip.open(
                dest, "wt", encoding="utf-8") as dst:
            for line in src:
                if not line.strip():
                    continue
                item = json.loads(line)
                if str(item.get("match_id")) not in keep:
                    continue
                item["quote_timestamp_proven"] = False
                item["research_only"] = True
                item["historical_price_semantics"] = "source_labeled_opener_or_unspecified"
                dst.write(json.dumps(item, ensure_ascii=False) + "\n")
                count += 1
        if count:
            sidecar_files.append(dest)
        else:
            dest.unlink()
        stats["sidecar_rows"] += count
    return stage_by_kind, sidecar_files, dict(stats)

def report(p: Path) -> dict:
    return json.loads((p / "report.json").read_text())

def parse_payload(value):
    if isinstance(value, dict):
        return value
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return {}
    if value == "":
        return {}
    return json.loads(value)

def immutable_market_gate(years: list[int]) -> dict:
    changed_rows = 0
    new_markers = Counter()
    annual = {}
    for year in years:
        name = f"history-{year}.parquet"
        x = pd.read_parquet(BEFORE / name).sort_values("match_id").reset_index(drop=True)
        y = pd.read_parquet(SHADOW / name).sort_values("match_id").reset_index(drop=True)
        if len(x) != len(y) or list(x.columns) != list(y.columns):
            raise RuntimeError("Schema or row count changed: " + name)
        allowed_col = "provider_payload_json"
        if allowed_col not in x:
            raise RuntimeError("Missing provider_payload_json column in " + name)
        for col in x:
            if col != allowed_col and not x[col].equals(y[col]):
                raise RuntimeError(f"Immutable column differs: {name}.{col}")
        count = 0
        for old, new in zip(x[allowed_col], y[allowed_col]):
            a = parse_payload(old)
            b = parse_payload(new)
            if not isinstance(a, dict) or not isinstance(b, dict):
                raise RuntimeError("Malformed provider payload")
            for k, v in a.items():
                if k not in b or b[k] != v:
                    raise RuntimeError("Pre-existing provider payload was overwritten")
            added = set(b).difference(a)
            if added - ALLOWED_MARKERS:
                raise RuntimeError("Unexpected added provider payload key")
            for key in added:
                if not isinstance(b[key], dict):
                    raise RuntimeError("Malformed new market payload")
                new_markers[key] += 1
            count += bool(added)
        changed_rows += count
        annual[str(year)] = count
    if changed_rows == 0 and years:
        raise RuntimeError("Changed partitions with no new market evidence")
    return {"verified_changed_matches": changed_rows,
            "new_market_markers": dict(new_markers),
            "per_year": annual, "new_matches": 0,
            "stats_unchanged": True, "rank_and_identity_unchanged": True,
            "existing_markets_unchanged": True}

def main():
    if not os.environ.get("GH_TOKEN"):
        raise RuntimeError("Private data repo access missing")
    if not json.loads(gh("api", f"repos/{DATA_REPO}")).get("private"):
        raise RuntimeError("Source or destination not private")
    ROOT.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    audit = {"schema": 1, "run_id": RUN_ID, "status": "running",
             "started_at_utc": datetime.now(timezone.utc).isoformat(),
             "canonical_mutated": False, "model_promoted": False,
             "api_requests": 0, "no_open_close_inference": True,
             "private_data_release": DATA_REPO}
    made_release = False
    try:
        audit["source"] = source_gate()
        run(sys.executable, "scripts/research/private_canonical_snapshot_v2.py")
        audit["backup_tag"] = BACKUP
        proof = json.loads((Path("work/private_canonical_backup") / "proof.json").read_text())
        if proof.get("status") != "source_verified" or not proof.get("private"):
            raise RuntimeError("No verified private canonical backup")
        ensure_same_as_backup(proof)
        store = ReleaseStore(DATA_REPO, "tbt-data-v1", BEFORE)
        store.download(require_bundle_manifest=True)
        if rows(BEFORE) != proof["row_count"]:
            raise RuntimeError("Canonical/backup row count mismatch")
        audit["canonical_before_rows"] = rows(BEFORE)
        SHADOW.mkdir(parents=True)
        for f in BEFORE.iterdir():
            if f.is_file():
                shutil.copy2(f, SHADOW / f.name)
        run(sys.executable, "private_data/scripts/stage_oddstrader_canonical.py",
            "--history-dir", SHADOW, "--source-dir", SOURCE, "--out-dir", STAGE)
        initial = report(STAGE)
        audit["linker_report"] = initial
        if initial["canonical_rows"] != audit["canonical_before_rows"]:
            raise RuntimeError("Linker canonical count mismatch")
        safe_stages, sidecars, filters = filter_linked(STAGE)
        audit["strict_exact_day"] = filters
        write_years = set()
        writes = Counter()
        for kind, importer in [
            ("opening", "scripts/import_offline_market_history.py"),
            ("fallback", "scripts/import_offline_linked_match_winner_odds.py"),
        ]:
            output = OUT / kind
            dry = OUT / (kind + "-dry")
            run(sys.executable, importer, "--stage", safe_stages[kind],
                "--history-dir", SHADOW, "--out-dir", dry)
            d = report(dry)
            rejected = [k for k in ("identity_missing", "identity_changed",
                                    "invalid_market", "invalid_market_history")
                        if d.get("counts", {}).get(k, 0)]
            if rejected:
                raise RuntimeError(f"Strict importer safety failure: {kind}/{rejected}")
            # Independent conflicts are quarantined and never overwritten.
            run(sys.executable, importer, "--stage", safe_stages[kind],
                "--history-dir", SHADOW, "--out-dir", output,
                "--write-partitions", "--write-history-dir", SHADOW)
            w = report(output)
            if d["counts"] != w["counts"] or d["changed_years"] != w["changed_years"]:
                raise RuntimeError("Dry-run and local-write delta differ: " + kind)
            audit[kind + "_report"] = w
            write_years.update(int(y) for y in w["changed_years"])
            writes[kind] += int(w.get("counts", {}).get("updated", 0))
        audit["local_written_markers"] = dict(writes)
        audit["changed_years"] = sorted(write_years)
        if rows(SHADOW) != audit["canonical_before_rows"]:
            raise RuntimeError("Local canonical row count mutated")
        audit["immutable_gate"] = immutable_market_gate(sorted(write_years))
        from tbt.data.history_snapshot import load_partitions
        from tbt.data.history_safety import sanitize_history_identities
        from tbt.services.data_quality import audit_history
        safe, identity = sanitize_history_identities(load_partitions(SHADOW))
        if identity.get("quarantined_rows") or len(safe) != audit["canonical_before_rows"]:
            raise RuntimeError("Identity integrity failed")
        accepted, quality = audit_history(safe)
        if len(accepted) != len(safe):
            raise RuntimeError("Data quality rejected shadow canonical rows")
        audit["quality_validation"] = {"accepted_rows": len(accepted),
                                      "identity_quarantine": identity.get("quarantined_rows", 0)}
        del accepted, safe
        ensure_same_as_backup(proof)
        audit["status"] = "strict_reconciliation_verified_before_publish"
        private_put(TARGET, audit)
        if write_years:
            years = sorted(write_years)
            paths = [SHADOW / f"history-{year}.parquet" for year in years] + [
                SHADOW / "history_manifest.json"]
            # No other history mutation after the sealed backup; abort if any
            # release partition changed in the meantime.
            store.upload_bundle(paths, before_upload=lambda: ensure_same_as_backup(proof))
            audit["canonical_mutated"] = True
        reloaded = ROOT / "readback"
        ReleaseStore(DATA_REPO, "tbt-data-v1", reloaded).download(require_bundle_manifest=True)
        if rows(reloaded) != audit["canonical_before_rows"]:
            raise RuntimeError("Persisted canonical row count differs")
        for year in sorted(write_years):
            name = f"history-{year}.parquet"
            if hash_file(SHADOW / name) != hash_file(reloaded / name):
                raise RuntimeError("Persisted canonical partition checksum failed: " + name)
        if write_years and hash_file(SHADOW / "history_manifest.json") != hash_file(
                reloaded / "history_manifest.json"):
            raise RuntimeError("Persisted canonical manifest checksum failed")
        audit["persisted_canonical_readback"] = "PASS"
        audit["canonical_after_rows"] = rows(reloaded)
        # Preserve matched historical bookmaker price information in a SEPARATE
        # private release. No raw quote data or sidecars in public tbt artifacts.
        if sidecars:
            sidecar_manifest = {"schema": 1, "source": "oddstrader",
                "run_id": RUN_ID, "quote_timestamps_verified": False,
                "training_eligible": False,
                "opening_semantics": "source_labeled_only",
                "canonical_rows": audit["canonical_after_rows"],
                "assets": {p.name: {"sha256": hash_file(p), "bytes": p.stat().st_size}
                           for p in sidecars}}
            m = STAGE / "oddstrader-sidecar-manifest.json"
            m.write_text(json.dumps(sidecar_manifest, indent=2))
            tag = "blinq-oddstrader-research-" + RUN_ID
            sha = json.loads(gh("api", f"repos/{DATA_REPO}/branches/main"))["commit"]["sha"]
            run("gh", "release", "create", tag, *sidecars, m,
                "--repo", DATA_REPO, "--target", sha, "--title",
                "Private OddsTrader match-linked research " + RUN_ID,
                "--notes", "Historical observational markets only. Unknown quote timestamps; no training or model promotion.")
            made_release = True
            audit["sidecar_release"] = tag
            audit["sidecar_assets"] = len(sidecars)
            remote = ROOT / "sidecar-readback"
            remote.mkdir()
            run("gh", "release", "download", tag, "--repo", DATA_REPO,
                "--dir", remote)
            for p in [*sidecars, m]:
                if hash_file(p) != hash_file(remote / p.name):
                    raise RuntimeError("Private sidecar remote checksum mismatch")
            audit["persisted_sidecar_readback"] = "PASS"
        audit["status"] = "verified_canonical_and_private_research_readback"
    except Exception as exc:
        audit["status"] = "blocked_or_failed"
        audit["error"] = str(exc)[:800]
        audit["sidecar_release_created"] = made_release
        if audit["canonical_mutated"]:
            audit["requires_manual_rollback_review"] = True
        raise
    finally:
        audit["finished_at_utc"] = datetime.now(timezone.utc).isoformat()
        private_put(TARGET, audit)
        print(json.dumps({"status": audit["status"], "canonical_mutated": audit["canonical_mutated"],
            "new_market_matches": audit.get("immutable_gate", {}).get("verified_changed_matches", 0),
            "sidecar_release": audit.get("sidecar_release"), "private_audit": TARGET},
            ensure_ascii=False), flush=True)

if __name__ == "__main__":
    main()
