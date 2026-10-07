"""Collect and fail-closed link CC0 Wikidata tennis identities.

This job intentionally writes research sidecars only. It never mutates canonical
history and never exposes Wikidata profile fields as model features.
"""
from __future__ import annotations

import argparse
import gzip
import json
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from _bootstrap import ROOT  # noqa: F401
from tbt.data.history_safety import sanitize_history_identities
from tbt.data.history_snapshot import load_partitions
from tbt.data.player_identity import build_canonical_players, normalize_player_name

WIKIDATA_ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "BlinQ-tennis-research/1.0 (non-commercial data quality research)"
LICENSE = "CC0-1.0"

SPARQL = r"""
SELECT DISTINCT ?item ?itemLabel ?birth ?countryAlpha3 ?hand
                ?atp ?wta ?itf ?itfOld ?tennisAbstract WHERE {
  ?item wdt:P31 wd:Q5 .
  {
    ?item wdt:P536 ?seed .
  } UNION {
    ?item wdt:P597 ?seed .
  } UNION {
    ?item wdt:P8618 ?seed .
  } UNION {
    ?item wdt:P599 ?seed .
  } UNION {
    ?item wdt:P10028 ?seed .
  }
  OPTIONAL { ?item wdt:P536 ?atp . }
  OPTIONAL { ?item wdt:P597 ?wta . }
  OPTIONAL { ?item wdt:P8618 ?itf . }
  OPTIONAL { ?item wdt:P599 ?itfOld . }
  OPTIONAL { ?item wdt:P10028 ?tennisAbstract . }
  OPTIONAL { ?item wdt:P569 ?birth . }
  OPTIONAL {
    ?item wdt:P27 ?country .
    OPTIONAL { ?country wdt:P298 ?countryAlpha3 . }
  }
  OPTIONAL { ?item wdt:P741 ?hand . }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
"""


def _binding_value(binding: dict[str, Any], key: str) -> str:
    node = binding.get(key)
    if not isinstance(node, dict):
        return ""
    return str(node.get("value") or "").strip()


def _qid(uri: str) -> str:
    return uri.rsplit("/", 1)[-1] if uri else ""


def fetch_sparql(*, attempts: int = 5, timeout: int = 90) -> dict[str, Any]:
    params = urllib.parse.urlencode({"query": SPARQL, "format": "json"})
    url = f"{WIKIDATA_ENDPOINT}?{params}"
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # network retry boundary
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(min(20, attempt * 4))
    raise RuntimeError(f"Wikidata SPARQL failed after {attempts} attempts: {last_error}")


def aggregate_profiles(payload: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    bindings = ((payload.get("results") or {}).get("bindings") or [])
    profiles: dict[str, dict[str, Any]] = {}
    conflicts = Counter()

    for binding in bindings:
        if not isinstance(binding, dict):
            continue
        qid = _qid(_binding_value(binding, "item"))
        label = _binding_value(binding, "itemLabel")
        if not qid.startswith("Q") or not label:
            continue
        row = profiles.setdefault(
            qid,
            {
                "schema": 1,
                "wikidata_qid": qid,
                "label": label,
                "normalized_label": normalize_player_name(label),
                "birth_dates": set(),
                "country_alpha3": set(),
                "hand_qids": set(),
                "atp_ids": set(),
                "wta_ids": set(),
                "itf_ids": set(),
                "itf_legacy_ids": set(),
                "tennis_abstract_ids": set(),
                "source": "Wikidata",
                "license": LICENSE,
            },
        )
        if row["label"] != label:
            conflicts["label_variants"] += 1

        mapping = {
            "birth": "birth_dates",
            "countryAlpha3": "country_alpha3",
            "atp": "atp_ids",
            "wta": "wta_ids",
            "itf": "itf_ids",
            "itfOld": "itf_legacy_ids",
            "tennisAbstract": "tennis_abstract_ids",
        }
        for source_key, target_key in mapping.items():
            value = _binding_value(binding, source_key)
            if value:
                row[target_key].add(value)
        hand = _qid(_binding_value(binding, "hand"))
        if hand.startswith("Q"):
            row["hand_qids"].add(hand)

    output: list[dict[str, Any]] = []
    for row in profiles.values():
        for key in (
            "birth_dates",
            "country_alpha3",
            "hand_qids",
            "atp_ids",
            "wta_ids",
            "itf_ids",
            "itf_legacy_ids",
            "tennis_abstract_ids",
        ):
            row[key] = sorted(row[key])
        output.append(row)

    output.sort(key=lambda item: item["wikidata_qid"])
    report = {
        "schema": 1,
        "source": "Wikidata",
        "license": LICENSE,
        "bindings": len(bindings),
        "profiles": len(output),
        "with_atp_id": sum(bool(r["atp_ids"]) for r in output),
        "with_wta_id": sum(bool(r["wta_ids"]) for r in output),
        "with_itf_id": sum(bool(r["itf_ids"]) for r in output),
        "with_tennis_abstract_id": sum(bool(r["tennis_abstract_ids"]) for r in output),
        "conflicts": dict(conflicts),
    }
    return output, report


def _tour_profiles(profiles: list[dict[str, Any]], tour: str) -> list[dict[str, Any]]:
    key = "atp_ids" if tour == "atp" else "wta_ids"
    return [row for row in profiles if row.get(key)]


def build_fail_closed_links(
    profiles: list[dict[str, Any]], history_dir: Path
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    matches, safety = sanitize_history_identities(load_partitions(history_dir))
    if safety.get("quarantined_rows"):
        raise RuntimeError("Canonical history identity quarantine is non-empty")

    links: list[dict[str, Any]] = []
    counts = Counter()

    for tour in ("atp", "wta"):
        canonical = build_canonical_players(matches, tour=tour)
        source = _tour_profiles(profiles, tour)

        source_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in source:
            name = str(row.get("normalized_label") or "")
            if name:
                source_by_name[name].append(row)

        canonical_name_owners: dict[str, set[str]] = defaultdict(set)
        for player in canonical:
            aliases = set(player.get("aliases") or [])
            aliases.add(str(player.get("name") or ""))
            for alias in aliases:
                norm = normalize_player_name(alias)
                if norm:
                    canonical_name_owners[norm].add(str(player["canonical_player_id"]))

        for player in canonical:
            pid = str(player["canonical_player_id"])
            aliases = set(player.get("aliases") or [])
            aliases.add(str(player.get("name") or ""))
            candidates: dict[str, dict[str, Any]] = {}
            matched_aliases: list[str] = []
            blocked_alias_collision = False

            for alias in aliases:
                norm = normalize_player_name(alias)
                if not norm:
                    continue
                if canonical_name_owners.get(norm) != {pid}:
                    blocked_alias_collision = True
                    continue
                rows = source_by_name.get(norm, [])
                if len(rows) == 1:
                    candidates[rows[0]["wikidata_qid"]] = rows[0]
                    matched_aliases.append(alias)
                elif len(rows) > 1:
                    counts["source_name_ambiguous"] += 1

            if len(candidates) != 1:
                counts["unmatched_or_ambiguous"] += 1
                if blocked_alias_collision:
                    counts["canonical_name_collision"] += 1
                continue

            chosen = next(iter(candidates.values()))
            row = {
                "schema": 1,
                "player_id": pid,
                "tour": tour,
                "canonical_name": player.get("name") or "",
                "wikidata_qid": chosen["wikidata_qid"],
                "wikidata_label": chosen["label"],
                "matched_aliases": sorted(set(matched_aliases)),
                "external_ids": {
                    "atp": chosen["atp_ids"],
                    "wta": chosen["wta_ids"],
                    "itf": chosen["itf_ids"],
                    "itf_legacy": chosen["itf_legacy_ids"],
                    "tennis_abstract": chosen["tennis_abstract_ids"],
                },
                "birth_dates": chosen["birth_dates"],
                "country_alpha3": chosen["country_alpha3"],
                "hand_qids": chosen["hand_qids"],
                "source": "Wikidata",
                "license": LICENSE,
                "evidence": "unique_exact_name_both_sides_plus_tour_specific_id",
                "feature_policy": "identity_research_sidecar_only",
            }
            links.append(row)
            counts["linked"] += 1
            counts[f"linked_{tour}"] += 1

    # A Wikidata item may map to at most one canonical player within each tour.
    seen: set[tuple[str, str]] = set()
    duplicates = []
    for row in links:
        key = (row["tour"], row["wikidata_qid"])
        if key in seen:
            duplicates.append(key)
        seen.add(key)
    if duplicates:
        raise RuntimeError(f"Duplicate canonical Wikidata links detected: {duplicates[:10]}")

    report = {
        "schema": 1,
        "source": "Wikidata",
        "license": LICENSE,
        "canonical_rows": len(matches),
        "counts": dict(counts),
        "identity_safety": safety,
        "production_mutated": False,
        "model_promoted": False,
        "link_policy": (
            "fail_closed: exact normalized name only; alias must be unique among canonical "
            "players in the same tour; Wikidata label must be unique among rows with the "
            "matching ATP/WTA identifier type; no fuzzy matching"
        ),
    }
    return sorted(links, key=lambda r: (r["tour"], r["player_id"])), report


def _write_jsonl_gz(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--history-dir", required=True)
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--source-json", default="")
    args = ap.parse_args()

    payload = (
        json.loads(Path(args.source_json).read_text(encoding="utf-8"))
        if args.source_json
        else fetch_sparql()
    )
    profiles, source_report = aggregate_profiles(payload)
    if len(profiles) < 1000:
        raise SystemExit(f"Wikidata profile count unexpectedly small: {len(profiles)}")

    links, link_report = build_fail_closed_links(profiles, Path(args.history_dir))
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    _write_jsonl_gz(out / "wikidata-tennis-identity.jsonl.gz", profiles)
    _write_jsonl_gz(out / "wikidata-canonical-links.jsonl.gz", links)

    report = {
        "schema": 1,
        "status": "verified",
        "source": "Wikidata",
        "license": LICENSE,
        "source_report": source_report,
        "link_report": link_report,
        "production_mutated": False,
        "model_promoted": False,
    }
    (out / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
