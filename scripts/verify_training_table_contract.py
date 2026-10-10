"""Fail-closed, executable gate shared by all canonical training table publishers."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

import pandas as pd

COLUMNS = (
    "match_id", "scheduled_at", "tour",
    "atp_hist_known_both", "wta_hist_known_both", "pre_match_weather_known",
)
RATES = {
    "atp": ("atp_hist_known_both", "atp_rank_history", 0.015),
    "wta": ("wta_hist_known_both", "wta_rank_history", 0.05),
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1048576), b""):
            h.update(b)
    return h.hexdigest()


def validate(frame: pd.DataFrame, report: dict, leakage: dict, *,
             weather_evidence: dict, research_ranks: bool = False) -> dict:
    absent = set(COLUMNS) - set(frame.columns)
    if absent:
        raise ValueError("Training schema missing: " + ", ".join(sorted(absent)))
    if not len(frame) or int(report.get("rows") or -1) != len(frame):
        raise ValueError("Training table/report row count mismatch")
    if frame["match_id"].isna().any() or frame["match_id"].duplicated().any():
        raise ValueError("Duplicate or missing training match identities")
    if leakage.get("status") not in {"pass", "PASS", "passed", "verified"}:
        raise ValueError("Leakage audit did not pass")
    if int(leakage.get("rows") or -1) != len(frame):
        raise ValueError("Leakage audit row count mismatch")
    if leakage.get("failed_checks") or leakage.get("posthoc_weather_training_violations"):
        raise ValueError("Leakage audit contains failed checks")
    ranks = report.get("verified_rank_inputs") or {}
    if not research_ranks:
        if ranks.get("status") != "verified" or ranks.get("provider_requests") != 0:
            raise ValueError("Missing checksum-verified private ranking provenance")
        sources = ranks.get("sources") or {}
        if not any("atp-rankings" in name for name in sources) or not any(
            "wta-rankings" in name for name in sources
        ):
            raise ValueError("Missing ranked source digests")
    else:
        if not (report.get("atp_rank_history") or {}).get("source"):
            raise ValueError("Research ATP ranking provenance missing")
        wta = report.get("wta_rank_history") or {}
        if not wta.get("ranking_csvs") or not wta.get("identity_crosswalk"):
            raise ValueError("Research WTA ranking provenance missing")
    if weather_evidence.get("status") != "verified":
        raise ValueError("Pre-match weather source not verified")
    if int(weather_evidence.get("provider_requests", 0)) < 0:
        raise ValueError("Invalid weather acquisition request count")
    if weather_evidence.get("fixed_forecast_lead_hours", weather_evidence.get("lead_hours")) != 24:
        raise ValueError("Pre-match weather is not fixed 24h lead")
    if (report.get("pre_match_forecast_weather") or {}).get("post_hoc_weather_used") is not False:
        raise ValueError("Post-hoc weather leakage")
    if int((report.get("pre_match_forecast_weather") or {}).get("lead_hours") or 0) != 24:
        raise ValueError("Training weather lead mismatch")

    date = pd.to_datetime(frame["scheduled_at"], utc=True, errors="coerce")
    if date.isna().any():
        raise ValueError("Training dates invalid")
    if date.min().isoformat() != pd.Timestamp(report["date_range"]["from"]).isoformat():
        raise ValueError("Training report minimum date differs")
    if date.max().isoformat() != pd.Timestamp(report["date_range"]["to"]).isoformat():
        raise ValueError("Training report maximum date differs")
    if not frame["tour"].isin(("atp", "wta")).all():
        raise ValueError("Unexpected tour")
    for column in COLUMNS[3:]:
        values = pd.to_numeric(frame[column], errors="coerce")
        if not values.isin([0.0, 1.0]).all():
            raise ValueError(f"Invalid binary coverage indicator: {column}")
    metrics = {}
    recent = date >= pd.Timestamp("2021-01-01", tz="UTC")
    for tour, (col, section, floor) in RATES.items():
        values = frame[col].astype(float)
        reported = float((report.get(section) or {}).get("known_both_rate") or 0)
        actual = float(values.mean())
        if not math.isclose(reported, actual, abs_tol=1e-6):
            raise ValueError(f"{tour} coverage report differs from table")
        if float(values[frame["tour"] != tour].sum()) != 0:
            raise ValueError(f"{tour} rank feature present on wrong tour")
        for period, scope in (("2021+", recent), ("2024+", date >= pd.Timestamp("2024-01-01", tz="UTC"))):
            mask = scope & frame["tour"].eq(tour)
            if int(mask.sum()) < 1000:
                raise ValueError(f"{tour} {period} coverage sample too small")
            rate = float(values[mask].mean())
            if rate < floor:
                raise ValueError(f"{tour} {period} rank-history coverage regression: {rate:.4f} < {floor}")
            metrics[f"{tour}_{period}"] = {"rows": int(mask.sum()), "known_both_rate": rate}
    weather = frame["pre_match_weather_known"].astype(float)
    weather_section = report.get("pre_match_forecast_weather") or {}
    if int(weather_section.get("known_rows") or -1) != int(weather.sum()):
        raise ValueError("Weather report rows differ from training table")
    modern = date >= pd.Timestamp("2024-01-01", tz="UTC")
    if modern.sum() < 1000 or float(weather[modern].mean()) < 0.05:
        raise ValueError("2024+ pre-match weather coverage regression")
    metrics["weather_2024+"] = {
        "rows": int(modern.sum()), "known_rate": float(weather[modern].mean())
    }
    return {"status": "verified", "rows": len(frame), "segments": metrics,
            "research_rank_mode": research_ranks}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--table", required=True, type=Path)
    p.add_argument("--report", required=True, type=Path)
    p.add_argument("--leakage", required=True, type=Path)
    p.add_argument("--weather-evidence", required=True, type=Path)
    p.add_argument("--weather-csv", type=Path)
    p.add_argument("--research-ranks", action="store_true")
    p.add_argument("--out", required=True, type=Path)
    a = p.parse_args()
    report = json.loads(a.report.read_text(encoding="utf-8"))
    leakage = json.loads(a.leakage.read_text(encoding="utf-8"))
    source = json.loads(a.weather_evidence.read_text(encoding="utf-8"))
    if not a.research_ranks:
        if a.weather_csv is None or not a.weather_csv.is_file():
            raise ValueError("Verified weather CSV must be supplied")
        if source.get("output_csv_sha256") != _sha256(a.weather_csv):
            raise ValueError("Verified weather CSV checksum mismatch")
        if source.get("provider_requests") != 0:
            raise ValueError("Unexpected provider calls during verified weather restore")
    required = list(COLUMNS)
    frame = pd.read_parquet(a.table, columns=required)
    result = validate(frame, report, leakage,
                      weather_evidence=source, research_ranks=a.research_ranks)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
