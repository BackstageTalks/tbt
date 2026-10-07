from __future__ import annotations

from pathlib import Path

import collect_wikidata_tennis_identity as mod


def _binding(qid: str, label: str, **values):
    row = {
        "item": {"type": "uri", "value": f"http://www.wikidata.org/entity/{qid}"},
        "itemLabel": {"type": "literal", "value": label},
    }
    for key, value in values.items():
        if value is not None:
            row[key] = {"type": "literal", "value": value}
    return row


def test_aggregate_profiles_deduplicates_bindings():
    payload = {
        "results": {
            "bindings": [
                _binding(
                    "Q1",
                    "Novak Djokovic",
                    atp="D643",
                    itf="novak-djokovic/800250878/srb",
                    tennisAbstract="NovakDjokovic",
                    birth="1987-05-22T00:00:00Z",
                    countryAlpha3="SRB",
                ),
                _binding(
                    "Q1",
                    "Novak Djokovic",
                    atp="D643",
                    countryAlpha3="SRB",
                ),
                _binding(
                    "Q2",
                    "Serena Williams",
                    wta="230234",
                    tennisAbstract="SerenaWilliams",
                    countryAlpha3="USA",
                ),
            ]
        }
    }

    rows, report = mod.aggregate_profiles(payload)
    assert len(rows) == 2
    assert report["profiles"] == 2
    assert report["with_atp_id"] == 1
    assert report["with_wta_id"] == 1
    djokovic = next(row for row in rows if row["wikidata_qid"] == "Q1")
    assert djokovic["atp_ids"] == ["D643"]
    assert djokovic["country_alpha3"] == ["SRB"]


def test_fail_closed_links_unique_exact_names(monkeypatch, tmp_path: Path):
    profiles = [
        {
            "wikidata_qid": "Q1",
            "label": "Novak Djokovic",
            "normalized_label": "novak djokovic",
            "birth_dates": [],
            "country_alpha3": ["SRB"],
            "hand_qids": [],
            "atp_ids": ["D643"],
            "wta_ids": [],
            "itf_ids": [],
            "itf_legacy_ids": [],
            "tennis_abstract_ids": ["NovakDjokovic"],
        },
        {
            "wikidata_qid": "Q2",
            "label": "Serena Williams",
            "normalized_label": "serena williams",
            "birth_dates": [],
            "country_alpha3": ["USA"],
            "hand_qids": [],
            "atp_ids": [],
            "wta_ids": ["230234"],
            "itf_ids": [],
            "itf_legacy_ids": [],
            "tennis_abstract_ids": ["SerenaWilliams"],
        },
    ]

    monkeypatch.setattr(mod, "load_partitions", lambda _: [object()])
    monkeypatch.setattr(
        mod,
        "sanitize_history_identities",
        lambda rows: (rows, {"quarantined_rows": 0}),
    )

    def fake_canonical(matches, *, tour, **kwargs):
        if tour == "atp":
            return [
                {
                    "canonical_player_id": "atp-1",
                    "name": "Novak Djokovic",
                    "aliases": ["Novak Djokovic"],
                }
            ]
        return [
            {
                "canonical_player_id": "wta-1",
                "name": "Serena Williams",
                "aliases": ["Serena Williams"],
            }
        ]

    monkeypatch.setattr(mod, "build_canonical_players", fake_canonical)
    links, report = mod.build_fail_closed_links(profiles, tmp_path)
    assert len(links) == 2
    assert report["counts"]["linked_atp"] == 1
    assert report["counts"]["linked_wta"] == 1
    assert report["production_mutated"] is False


def test_fail_closed_blocks_canonical_name_collision(monkeypatch, tmp_path: Path):
    profiles = [
        {
            "wikidata_qid": "Q3",
            "label": "Alex Smith",
            "normalized_label": "alex smith",
            "birth_dates": [],
            "country_alpha3": [],
            "hand_qids": [],
            "atp_ids": ["A001"],
            "wta_ids": [],
            "itf_ids": [],
            "itf_legacy_ids": [],
            "tennis_abstract_ids": [],
        }
    ]
    monkeypatch.setattr(mod, "load_partitions", lambda _: [object()])
    monkeypatch.setattr(
        mod,
        "sanitize_history_identities",
        lambda rows: (rows, {"quarantined_rows": 0}),
    )

    def fake_canonical(matches, *, tour, **kwargs):
        if tour == "atp":
            return [
                {"canonical_player_id": "p1", "name": "Alex Smith", "aliases": []},
                {"canonical_player_id": "p2", "name": "Alex Smith", "aliases": []},
            ]
        return []

    monkeypatch.setattr(mod, "build_canonical_players", fake_canonical)
    links, report = mod.build_fail_closed_links(profiles, tmp_path)
    assert links == []
    assert report["counts"]["canonical_name_collision"] == 2
