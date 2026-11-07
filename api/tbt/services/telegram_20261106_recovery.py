"""One-shot Nov 6 Telegram ACE results recovery from already verified archive counts.

No provider API requests, CDB mutations, daily feed rewrites, guessed statistics,
or Telegram sends. A frozen private delivery receipt is corroborated by the
independently checked November 6 archive audit. Write only via the existing
provider-verification-aware append-only Results CAS archive interface.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import math

from tbt.services.results_archive import (
    _archive_record, _identity, load_settled_results_archive, save_settled_results_archive,
)

DAY = "2026-11-06"
ISSUED_AT = "2026-11-06T06:44:03.058515+00:00"
FROZEN_TELEGRAM_MESSAGE_IDS = (737, 738)
# (event, chosen player ID, original name, UTC start, Over line, projection,
#  issued local decimal odds, actual player Aces confirmed by 2026-11-07
#  zero-provider strict archive audit run 42353354060).
FROZEN_ACE_REFS = (
    ("17428210", "136042", "Taylor Fritz", "18:00", 9.5, 10.54, 1.69, 12),
    ("17501298", "387855", "Oskar Brostrom Poulsen", "17:00", 5.5, 7.49, 1.65, 7),
    ("17497710", "102817", "Niels Lootsma", "08:40", 4.5, 6.03, 1.79, 6),
    ("17427360", "309071", "Jerome Kym", "13:20", 6.5, 8.12, 1.76, 12),
    ("17427662", "42289", "Magda Linette", "11:50", 2.5, 4.0, 1.64, 6),
    ("17428201", "385485", "Ben Shelton", "13:00", 8.5, 10.29, 1.72, 19),
    ("17501300", "373228", "Eric David Verdes", "15:00", 3.5, 5.0, 1.69, 4),
    ("17497371", "233680", "Rafael Kis Balázs", "09:50", 4.5, 6.18, 1.77, 9),
)
# The 3 TOP issues (FREE is a fourth ledger entry mirroring the second TOP).
FROZEN_TOP_REFS = (
    ("17498376", "200791"),
    ("17501482", "403371"),
    ("17498231", "195414"),
)


def _utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Recovery timestamps require timezone")
    return parsed.astimezone(timezone.utc)


def _verified_count_evidence(
    archive: list[dict], event_id: str, selection_id: str,
    scheduled_at: str, expected_count: int,
) -> dict:
    """Exactly one final exact-player *provider-verified* source publication."""
    matches = []
    for row in archive:
        if not isinstance(row, dict):
            continue
        if (str(row.get("event_id") or "") != event_id
                or str(row.get("scheduled_at") or "") != scheduled_at):
            continue
        players = [row.get("player1"), row.get("player2")]
        if (not all(isinstance(p, dict) for p in players)
                or any(not str(p.get("id") or "") for p in players)
                or players[0]["id"] == players[1]["id"]
                or selection_id not in {str(p["id"]) for p in players}):
            continue
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict):
                continue
            if (str(pub.get("section") or "") != "ace"
                    or str(pub.get("market") or "") != "aces"
                    or str(pub.get("selection_id") or "") != selection_id
                    or pub.get("publication_status", "published") != "published"):
                continue
            result = pub.get("result")
            if (not isinstance(result, dict)
                    or result.get("runtime_source") != "match_status_snapshot"
                    or result.get("recovery_evidence")
                        == "existing_verified_exact_player_aces_count_v1"
                    or type(result.get("correct")) is not bool
                    or result.get("void") is True):
                continue
            raw = result.get("actual_count")
            if isinstance(raw, bool) or raw is None:
                continue
            try:
                actual = float(raw)
            except (TypeError, ValueError, OverflowError):
                continue
            if not math.isfinite(actual) or actual < 0 or not actual.is_integer():
                continue
            # The actual was sourced by the existing runtime worker's
            # provider-ID-matched player statistic, not a match winner.
            if int(actual) == expected_count:
                matches.append((row, pub, result))
            else:
                raise ValueError("Conflicting source-native Aces count: " + event_id)
    if len(matches) != 1:
        raise ValueError("Unique verified source Aces evidence absent: " + event_id)
    row, pub, result = matches[0]
    if str(result.get("reason") or "").lower() in {"retired", "void", "walkover"}:
        raise ValueError("Indeterminate retirement settlement: " + event_id)
    return {"row": row, "publication": pub, "result": result}


def _top_readback(archive: list[dict]) -> int:
    verified = set()
    for row in archive:
        if not isinstance(row, dict):
            continue
        event = str(row.get("event_id") or "")
        for pub in row.get("market_publications") or []:
            if not isinstance(pub, dict):
                continue
            selection = str(pub.get("selection_id") or "")
            result = pub.get("result") or {}
            if (event, selection) in FROZEN_TOP_REFS and (
                str(row.get("scheduled_at") or "").startswith(DAY + "T")
                and pub.get("publication_status", "published") == "published"
                and str(pub.get("section") or "") == "top_daily"
                and str(pub.get("market") or "") == "match_winner"
                and result.get("runtime_source") == "match_status_snapshot"
                and (type(result.get("correct")) is bool
                     or result.get("void") is True)
            ):
                verified.add((event, selection))
    if verified != set(FROZEN_TOP_REFS):
        raise ValueError("All original TOP and FREE source results must already exist")
    return len(verified)


def exact_candidates(archive: list[dict]) -> list[dict]:
    """Rebuild *only* the original 8 sent O/U terms from the immutable ledger."""
    if len(FROZEN_ACE_REFS) != 8 or len({item[0] for item in FROZEN_ACE_REFS}) != 8:
        raise RuntimeError("Frozen November 6 issuance manifest changed")
    checked = _top_readback(archive)
    assert checked == 3
    issued = _utc(ISSUED_AT)
    candidates = []
    for event, selection, name, clock, line, projection, odds, actual in FROZEN_ACE_REFS:
        scheduled = f"{DAY}T{clock}:00+00:00"
        if issued >= _utc(scheduled) or not (1.60 <= odds <= 1.80):
            raise ValueError("Original Telegram price or issuance time invalid")
        if actual <= line:
            # A future audit change cannot silently flip a prior verified
            # win into a new result without an independently reviewed correction.
            raise ValueError("Frozen count/line witness contradicts audit")
        proof = _verified_count_evidence(archive, event, selection, scheduled, actual)
        source_row = proof["row"]
        original_result = proof["result"]
        pub_key = f"local-aces-ou-v1:{event}:{selection}:over:{line:.1f}"
        source_pub = {
            "section": "ace", "market": "aces", "selection_id": selection,
            "publication_key": pub_key, "publication_status": "published",
            "price_contract": "player_total_ou", "ou_side": "over",
            "market_line": line, "selection": f"{name} Over {line:.1f} Aces",
            "projection_scope": "player", "projection_metric": "aces",
            "projection": projection, "issued_at": ISSUED_AT,
            "odds": odds, "price_status": "priced_projection",
            "price_basis": "local_aces_statistical_v1",
            "source": "confirmed_telegram_ou_reissue",
        }
        # Use exactly the previously verified same-player source measurement.
        # Do not assert an invented match-winner status or infer missing stats.
        result = {
            "status": "hit", "correct": True, "void": False,
            "actual_count": actual,
            "settled_at": original_result.get("settled_at"),
            "scheduled_at": scheduled,
            "runtime_overlay": True,
            "runtime_source": "match_status_snapshot",
            "recovery_evidence": "existing_verified_exact_player_aces_count_v1",
            "projection_scope": "player", "projection_metric": "aces",
            "projection": projection, "staked_units": 1.0,
            "return_units": odds, "profit_units": round(odds - 1.0, 8),
        }
        if original_result.get("retirement_line_decided") is True:
            result["retirement_line_decided"] = True
            result["reason"] = "retired_after_ou_decided"
        row = {
            key: deepcopy(source_row[key])
            for key in ("event_id", "scheduled_at", "betting_day", "tour",
                        "tournament", "tournament_id", "round", "surface")
            if key in source_row
        }
        row.update(
            event_id=event, scheduled_at=scheduled, betting_day=DAY,
            player1=deepcopy(source_row["player1"]),
            player2=deepcopy(source_row["player2"]),
            market_publications=[{**source_pub, "result": result}],
            runtime_result_overlay=True,
            archive_source="verified_match_status_snapshot",
        )
        native = _archive_record(row, row["market_publications"][0], ISSUED_AT)
        if native is None:
            raise ValueError("Native archive rejected original frozen Aces contract")
        candidates.append(native)
    return candidates


def recover(*, dry_run: bool = True) -> dict:
    """Strict dry-run followed by native CAS append and full independent readback."""
    before = load_settled_results_archive()
    candidates = exact_candidates(before)
    expected_by_key = {
        _identity(row, row["market_publications"][0]): row
        for row in candidates
    }
    if len(expected_by_key) != 8 or not all(expected_by_key):
        raise RuntimeError("Invalid or duplicated frozen recovery identity")
    prior_by_key: dict[str, list[dict]] = {}
    for row in before:
        for pub in row.get("market_publications") or []:
            key = _identity(row, pub)
            if key in expected_by_key:
                prior_by_key.setdefault(key, []).append(pub)
    new_rows = []
    for key, candidate in expected_by_key.items():
        matches = prior_by_key.get(key, [])
        if len(matches) > 1:
            raise RuntimeError("Duplicate exact original archive contract")
        if not matches:
            new_rows.append(candidate)
            continue
        old = matches[0]
        exact = candidate["market_publications"][0]
        if any(old.get(k) != exact.get(k) for k in (
            "publication_key", "market_line", "ou_side", "odds", "issued_at",
            "price_basis", "selection_id",
        )):
            raise RuntimeError("Conflicting existing original issued contract")
        result = old.get("result") or {}
        if any(result.get(k) != exact["result"].get(k) for k in (
            "runtime_source", "correct", "void", "actual_count",
            "staked_units", "profit_units",
        )):
            raise RuntimeError("Conflicting previously archived ACE result")
    planned = {
        "day": DAY, "telegram_receipt_ids": list(FROZEN_TELEGRAM_MESSAGE_IDS),
        "expected_aces": 8, "top_verified": 3,
        "verified_unique_player_counts": 8,
        "previous_exact_aces": 8 - len(new_rows),
        "net_new_aces": len(new_rows),
        "provider_requests": 0, "cdb_writes": 0, "telegram_sent": False,
        "mutation_permitted": not dry_run,
    }
    if dry_run:
        return {"status": "dry_run", **planned}
    if new_rows:
        write = save_settled_results_archive(new_rows)
        if (write.get("verified") is not True
                or write.get("added") != len(new_rows)
                or write.get("updated") != 0):
            raise RuntimeError("Append-only archive CAS did not verify exact writes")
    after = load_settled_results_archive()
    found = {}
    for row in after:
        for pub in row.get("market_publications") or []:
            key = _identity(row, pub)
            if key in expected_by_key:
                found.setdefault(key, []).append(pub)
    for key, expected in expected_by_key.items():
        pubs = found.get(key) or []
        if len(pubs) != 1:
            raise RuntimeError("Independent original ACE archive readback ambiguous")
        stored = pubs[0]
        frozen = expected["market_publications"][0]
        if any(stored.get(k) != frozen.get(k) for k in (
            "publication_key", "market_line", "ou_side", "odds", "issued_at",
            "selection_id",
        )) or any((stored.get("result") or {}).get(k) != frozen["result"].get(k)
                  for k in ("runtime_source", "correct", "void", "actual_count",
                            "staked_units", "profit_units")):
            raise RuntimeError("Exact original ACE settlement readback mismatch")
    return {"status": "verified", "archived_original_aces": len(found), **planned}
