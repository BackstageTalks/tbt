"""Independent, read-only second-pass audit of the verified comparator directory.

No API requests, canonical writes, ID merges or model changes. The CI reproducer
must first download and hash-verify the private comparator release.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from tbt.data.player_identity import normalize_player_name
from tbt.services.comparator_runtime import (
    _abbreviated_name_key,
    _full_name_key,
    _safe_abbreviation_target,
    search_players,
)

DIRECTORY = Path("/tmp/blinq-comparator-readonly-audit/comparator-players.json")


def _provider(row: dict) -> bool:
    return not str(row.get("player_id") or "").startswith("hist-js:")


def inspect(players: list[dict]) -> dict:
    counts = Counter()
    examples = defaultdict(list)
    names = defaultdict(list)
    aliases = defaultdict(set)
    full_by_initial = defaultdict(list)
    provider_full = defaultdict(list)
    reverse_names = defaultdict(list)
    compound = defaultdict(list)
    provider_ids_by_tour = defaultdict(set)

    def keep(reason: str, item: dict, *, max_examples: int = 8):
        if len(examples[reason]) < max_examples:
            examples[reason].append(item)

    for p in players:
        tour = str(p.get("tour") or "").lower()
        pid = str(p.get("player_id") or "").strip()
        norm = normalize_player_name(p.get("name"))
        if tour not in {"atp", "wta"} or not pid or not norm:
            counts["malformed_player_rows"] += 1
            continue
        counts["directory_rows"] += 1
        counts[f"{tour}_rows"] += 1
        counts["provider_rows" if _provider(p) else "historical_rows"] += 1
        if _provider(p):
            provider_ids_by_tour[tour].add(pid)
        names[tour, norm].append(p)
        for name in p.get("aliases") or []:
            a = normalize_player_name(name)
            if a:
                aliases[tour, a].add(pid)
        key = _full_name_key(p.get("name"))
        if key:
            full_by_initial[tour, key].append(p)
            if _provider(p):
                provider_full[tour, norm].append(p)
        tokens = norm.split()
        if len(tokens) == 2 and len(tokens[0]) > 1 and len(tokens[1]) > 1:
            reverse_names[tour, norm].append(p)
        if len(tokens) >= 3 and len(tokens[0]) > 1:
            for inner in tokens[1:-1]:
                if len(inner) > 1:
                    compound[tour, tokens[0][0], inner].append(p)

    # Full spelling collisions are distinct from spelling normalisation or
    # actual proven identity equivalence: count, never merge.
    for (tour, name), group in names.items():
        distinct = {str(p["player_id"]): p for p in group}
        if len(distinct) < 2:
            continue
        counts["multi_id_same_spelling_groups"] += 1
        providers = [p for p in distinct.values() if _provider(p)]
        if len(providers) > 1:
            counts["multi_provider_same_name_groups"] += 1
            keep("multi_provider_same_name", {"tour": tour, "name": name, "ids": [p["player_id"] for p in providers[:6]]})
        elif len(providers) == 1:
            counts["provider_historical_same_name_groups"] += 1
        else:
            counts["historical_only_same_name_groups"] += 1
        spellings = {str(p.get("name")) for p in distinct.values()}
        if len(spellings) > 1:
            counts["multi_id_accent_case_variations"] += 1
            keep("accent_case_variations", {"tour": tour, "names": sorted(spellings)[:6]})

    for (tour, norm), group in names.items():
        if len(norm.split()) != 2 or " ".join(reversed(norm.split())) == norm:
            continue
        reversed_key = (tour, " ".join(reversed(norm.split())))
        flipped = reverse_names.get(reversed_key, [])
        if flipped and norm < reversed_key[1]:
            counts["reversed_two_token_name_pairs"] += 1
            keep("reversed_name", {"tour": tour, "normal": [p["name"] for p in group[:2]], "reverse": [p["name"] for p in flipped[:2]]})

    for (tour, alias), ids in aliases.items():
        if len(ids) < 2:
            continue
        # Only count aliases naming several provider rows when actual provider
        # identity ambiguity exists; historic fragments remain separate.
        matching_provider_ids = ids & provider_ids_by_tour[tour]
        if len(matching_provider_ids) >= 2:
            counts["multi_provider_alias_conflicts"] += 1
            keep("provider_alias_conflict", {"tour": tour, "alias": alias, "provider_ids": sorted(matching_provider_ids)[:5]})

    safe_queries = []
    for row in players:
        tour = str(row.get("tour") or "").lower()
        short_key = _abbreviated_name_key(row.get("name"))
        if tour not in {"atp", "wta"} or short_key is None:
            continue
        counts["abbreviated_rows"] += 1
        full_candidates = full_by_initial[tour, short_key]
        target = _safe_abbreviation_target(row, full_candidates)
        distinct_names = {normalize_player_name(p.get("name")) for p in full_candidates}
        if target is not None:
            counts["safe_display_abbreviations"] += 1
            safe_queries.append((tour, row, target))
            full_id = str(target.get("player_id") or "")
            ranks = (row.get("rank"), target.get("rank"))
            try:
                ranks_agree = min(int(ranks[0]), int(ranks[1])) > 0 and abs(int(ranks[0]) - int(ranks[1])) <= 10
            except (ValueError, TypeError):
                ranks_agree = False
            full_name = normalize_player_name(target.get("name"))
            alias_agrees = full_name in {normalize_player_name(a) for a in row.get("aliases") or []}
            hist_corrob = (
                str(row.get("player_id") or "").startswith("hist-js:")
                and len({str(p.get("player_id")) for p in full_candidates}) > 1
                and len({normalize_player_name(p.get("name")) for p in full_candidates}) == 1
                and len([p for p in full_candidates if _provider(p)]) == 1
            )
            if alias_agrees:
                counts["safe_with_explicit_alias"] += 1
            if ranks_agree:
                counts["safe_with_rank_proximity"] += 1
            if hist_corrob:
                counts["safe_with_full_history_provenance"] += 1
            if not alias_agrees and not hist_corrob:
                counts["rank_only_presentation"] += 1
                keep("rank_only", {"short": row.get("name"), "full": target.get("name"), "tour": tour, "ranks": ranks})
            if not _provider(target):
                counts["safe_target_historical_only"] += 1
                keep("historical_target", {"short": row.get("name"), "full": target.get("name")})
            if len(distinct_names) > 1:
                counts["unsafe_false_link"] += 1
        elif not full_candidates:
            counts["abbreviation_missing_full"] += 1
            candidates = compound.get((tour, *short_key), [])
            if candidates:
                counts["compound_surname_candidates"] += 1
                keep("compound_surname", {"short": row.get("name"), "tour": tour, "candidates": [p.get("name") for p in candidates[:4]]})
        elif len(distinct_names) > 1:
            counts["ambiguous_abbreviation_homonyms"] += 1
            keep("ambiguous_abbreviation", {"short": row.get("name"), "candidates": [p.get("name") for p in full_candidates[:5]]})
        else:
            counts["not_verified_abbreviation"] += 1

    # Real exact-query contract against the full 25k-player directory, not
    # synthetic test data. Explicitly test every approved abbreviated name.
    for tour, short, target in safe_queries:
        result = search_players({"players": players}, short.get("name") or "", tour=tour, limit=25)
        if not result or str(result[0].get("player_id")) != str(target.get("player_id")):
            counts["search_mapping_failures"] += 1
            keep("mapping_failure", {
                "short": short.get("name"), "tour": tour,
                "wanted": target.get("player_id"),
                "got": [x.get("player_id") for x in result[:4]],
            })

    return {"counts": dict(counts), "examples": dict(examples)}


def main():
    if not DIRECTORY.is_file():
        raise RuntimeError("Verified comparator directory missing; abort second pass")
    raw = DIRECTORY.read_bytes()
    payload = json.loads(raw)
    players = payload.get("players")
    if not isinstance(players, list) or not players:
        raise RuntimeError("Empty or invalid comparator directory")
    report = inspect(players)
    report["snapshot_sha256"] = hashlib.sha256(raw).hexdigest()
    report["generated_at"] = payload.get("generated_at")
    report["model_version"] = payload.get("model_version")
    print("COMPARATOR_SECOND_PASS " + json.dumps(report, ensure_ascii=False, sort_keys=True), flush=True)
    counts = report["counts"]
    if counts.get("unsafe_false_link") or counts.get("search_mapping_failures"):
        raise RuntimeError("Unsafe comparator name mapping detected in production directory")


if __name__ == "__main__":
    main()
