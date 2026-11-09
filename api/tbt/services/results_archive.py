"""Durable, issuer-safe Results overlay for settled public predictions.

Azure Table is the append-only serving sidecar. The canonical predictions release
and its original issued odds/ledger remain immutable during hourly status checks.
Every row originates from a deployed pick and provider-confirmed terminal
match/statistics evidence. Per-day shards avoid the Azure 64-KiB string ceiling.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
import math
from typing import Any

from .admin_storage import (
    AdminStorageUnavailable, UI_TABLE, _table, _storage_not_found,
    _encode_runtime_ui_payload, _decode_runtime_ui_payload,
)
from .match_status import runtime_settled_results, verified_terminal_statuses

_PARTITION = "settled-results-archive-v1"
_PUBLIC_SECTIONS = {"top_daily", "prime", "value", "doubles", "ace", "ace_winner", "double_faults", "sets", "games"}
_SHARDS = 4
_MAX_ROW_UTF16 = 60_000
_MAX_ARCHIVED_ROWS = 12_000
_PLAYER_KEYS = (
    "id", "name", "country", "country_code", "country_code2",
    "country_code3", "photo", "photo_url", "image", "image_url",
    "avatar", "rank",
)
_ROW_KEYS = (
    "event_id", "id", "scheduled_at", "date", "tour", "tournament",
    "tournament_id", "tournament_logo", "tournament_logo_url",
    "surface", "round", "competition", "prediction_family",
    "betting_day", "is_doubles",
)


def _time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
        return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def _identity(row: dict, publication: dict) -> str:
    event = str(row.get("event_id") or row.get("id") or "").strip()
    section = str(publication.get("section") or "").strip().lower()
    market = str(publication.get("market") or "match_winner").strip().lower()
    scope = str(publication.get("projection_scope") or "").strip().lower()
    metric = str(publication.get("projection_metric") or "").strip().lower()
    selection = str(publication.get("selection_id") or publication.get("winner_id") or "").strip()
    if not (event and section and market and selection):
        return ""
    base = "|".join((event, section, market, scope, metric, selection))
    if market in {"aces", "most_aces", "double_faults", "sets", "games"}:
        # An immutable O/U market line is part of the bet identity. The
        # selection alone cannot distinguish Over 4.5 from Under 5.5.
        contract = str(publication.get("publication_key") or "").strip()
        if contract:
            return base + "|" + contract
        direction = str(publication.get("ou_side") or publication.get("projection_direction") or "").lower()
        threshold = publication.get("market_line") if market in {"aces", "double_faults"} else publication.get("reference_projection")
        return base + "|" + str(publication.get("price_contract") or "") + "|" + direction + "|" + str(threshold)
    return base


def _archive_record(row: dict, publication: dict, generated_at: str) -> dict | None:
    if not isinstance(row, dict) or not isinstance(publication, dict):
        return None
    identity = _identity(row, publication)
    if not identity or str(publication.get("section") or "").lower() not in _PUBLIC_SECTIONS:
        return None
    market = str(publication.get("market") or "match_winner").lower()
    section = str(publication.get("section") or "").lower()
    if market != "match_winner" and not (
        market in {"aces", "most_aces", "double_faults", "sets", "games"}
        and section == {"aces":"ace", "most_aces":"ace_winner", "double_faults":"double_faults", "sets":"sets", "games":"games"}[market]
    ):
        return None
    result = publication.get("result")
    if not isinstance(result, dict) or result.get("runtime_source") != "match_status_snapshot":
        return None
    if result.get("correct") not in (True, False) and not result.get("void"):
        return None
    scheduled = _time(row.get("scheduled_at") or row.get("date"))
    if scheduled is None:
        return None
    # Fail closed for later publications. A legacy deployed daily offer may
    # omit issued_at; its immutable morning feed generation must predate play.
    issued = _time(publication.get("issued_at")) if publication.get("issued_at") else None
    if publication.get("issued_at") and issued is None:
        return None
    if issued is None:
        if publication.get("runtime_publication_evidence") != "deployed_daily_offer_row":
            return None
        issued = _time(generated_at)
    if issued is None or issued > scheduled:
        return None
    player = lambda p: {k: deepcopy(v) for k, v in (p or {}).items() if k in _PLAYER_KEYS} if isinstance(p, dict) else {}
    stored = {k: deepcopy(row[k]) for k in _ROW_KEYS if k in row}
    stored["player1"] = player(row.get("player1"))
    stored["player2"] = player(row.get("player2"))
    stored["market_publications"] = [deepcopy(publication)]
    stored["runtime_result_overlay"] = True
    stored["archive_source"] = "verified_match_status_snapshot"
    return stored


def settled_archive_candidates(feed: dict, statuses: dict) -> list[dict]:
    """Materialize exclusively already deployed and verified terminal picks."""
    verified = verified_terminal_statuses(statuses)
    if not verified:
        return []
    # Historical feed rows are never reissued or archived as fresh picks.
    source = {**feed, "results": []}
    runtime = runtime_settled_results(source, verified)
    generated_at = str(feed.get("generated_at") or "")
    unique = {}
    for row in runtime:
        if not row.get("runtime_result_overlay"):
            continue
        for publication in row.get("market_publications") or []:
            stored = _archive_record(
                row, publication,
                str(row.get("_issued_rollover_generated_at") or generated_at),
            )
            if stored is not None:
                unique[_identity(stored, stored["market_publications"][0])] = stored
    return list(unique.values())


def _slot(row: dict) -> tuple[str, str]:
    publication = row["market_publications"][0]
    key = _identity(row, publication)
    moment = _time(row.get("scheduled_at") or row.get("date"))
    if not key or moment is None:
        raise AdminStorageUnavailable("Invalid settled-results archive identity")
    bucket = int(sha256(key.encode("utf-8")).hexdigest()[:8], 16) % _SHARDS
    return f"{moment.date().isoformat()}-{bucket:02d}", key


def _cas_conflict(exc: Exception) -> bool:
    """Azure/Firestore version conflicts only; never retry unrelated failures."""
    status = getattr(exc, "status_code", None)
    return status in (409, 412) or type(exc).__name__.lower() in {
        "resourceexistserror", "resourcemodifiederror", "storagerequesterror",
    } and status in (409, 412)


def save_settled_results_archive(rows: list[dict]) -> dict:
    """CAS append/merge with bounded retry and full persisted-shard readback.

    Never use a blind Azure Table upsert for an archive shard: a concurrent
    match-status worker could otherwise erase a different verified result.
    Only retry version conflicts after rereading the entire authoritative row.
    """
    from azure.core import MatchConditions

    groups = {}
    for row in rows:
        slot, key = _slot(row)
        groups.setdefault(slot, {})[key] = row
    if not groups:
        return {"eligible": 0, "added": 0, "updated": 0, "verified": True}
    try:
        table = _table(UI_TABLE)
        added = updated = 0
        for slot, incoming in sorted(groups.items()):
            for attempt in range(8):
                previous = None
                try:
                    previous = table.get_entity(partition_key=_PARTITION, row_key=slot)
                    old = _decode_runtime_ui_payload(str(previous.get("payload") or ""))
                    if not isinstance(old, dict) or old.get("schema") != 1 or not isinstance(old.get("rows"), dict):
                        raise AdminStorageUnavailable("Corrupt result archive; refusing overwrite")
                    records = old["rows"]
                except Exception as exc:
                    if isinstance(exc, AdminStorageUnavailable):
                        raise
                    if not _storage_not_found(exc):
                        raise
                    records = {}

                combined = dict(records)
                changed = False
                slot_added = slot_updated = 0
                for key, row in incoming.items():
                    if combined.get(key) != row:
                        if key in combined:
                            slot_updated += 1
                        else:
                            slot_added += 1
                        combined[key] = row
                        changed = True
                if not changed:
                    break

                encoded = _encode_runtime_ui_payload({"schema": 1, "rows": combined})
                if len(encoded.encode("utf-16-le")) > _MAX_ROW_UTF16:
                    raise AdminStorageUnavailable("Result archive shard exceeded Azure property limit")
                entity = {
                    "PartitionKey": _PARTITION, "RowKey": slot,
                    "payload": encoded,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
                try:
                    if previous is None:
                        # Create must reject an unseen concurrent create. Using
                        # upsert here would reintroduce lost-update races.
                        table.create_entity(entity)
                    else:
                        etag = getattr(previous, "metadata", {}).get("etag")
                        if etag is None:
                            raise AdminStorageUnavailable("Results archive ETag unavailable; refusing unsafe overwrite")
                        table.update_entity(
                            entity, mode="merge", etag=etag,
                            match_condition=MatchConditions.IfNotModified,
                        )
                except AdminStorageUnavailable:
                    raise
                except Exception as exc:
                    if _cas_conflict(exc):
                        if attempt < 7:
                            continue
                        raise AdminStorageUnavailable("Results archive CAS retry exhausted") from exc
                    raise

                # Independently reread the *whole proposed shard*, including
                # previous third-party rows, not just the new incoming items.
                persisted = table.get_entity(partition_key=_PARTITION, row_key=slot)
                recovered = _decode_runtime_ui_payload(str(persisted.get("payload") or ""))
                remote_rows = recovered.get("rows") if isinstance(recovered, dict) else None
                if not isinstance(remote_rows, dict) or any(
                    remote_rows.get(key) != row for key, row in combined.items()
                ):
                    raise AdminStorageUnavailable("Result archive persisted CAS readback failed")
                added += slot_added
                updated += slot_updated
                break
            else:
                raise AdminStorageUnavailable("Results archive CAS retry exhausted")
        return {"eligible": len(rows), "added": added, "updated": updated, "verified": True}
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to persist match results archive") from exc


def load_settled_results_archive() -> list[dict]:
    """Read durable Results; never infer settlements from unfinished matches."""
    try:
        table = _table(UI_TABLE)
        records = {}
        for item in table.query_entities(f"PartitionKey eq '{_PARTITION}'"):
            if len(records) > _MAX_ARCHIVED_ROWS:
                raise AdminStorageUnavailable("Result archive exceeds safe read limit")
            parsed = _decode_runtime_ui_payload(str(item.get("payload") or ""))
            if not isinstance(parsed, dict) or parsed.get("schema") != 1 or not isinstance(parsed.get("rows"), dict):
                raise AdminStorageUnavailable("Unreadable results archive shard")
            for key, row in parsed["rows"].items():
                if isinstance(row, dict) and row.get("market_publications"):
                    records[key] = row
        return list(records.values())
    except AdminStorageUnavailable:
        raise
    except Exception as exc:
        raise AdminStorageUnavailable("Unable to load match results archive") from exc



def read_only_archive_category_counts(
    archived: list[dict], *, now: datetime | None = None,
) -> dict:
    """Aggregate-only category readback for diagnosing Results filters.

    No user, event or selection identifiers are returned; this function does
    not mutate the Azure archive or infer settlements.
    """
    from collections import Counter
    from datetime import timedelta
    from zoneinfo import ZoneInfo

    bratislava = ZoneInfo("Europe/Bratislava")
    clock = (now or datetime.now(timezone.utc)).astimezone(bratislava)

    def day_key(moment: datetime) -> str:
        local = moment.astimezone(bratislava)
        if local.hour < 6:
            local -= timedelta(days=1)
        return local.date().isoformat()

    current_day = day_key(clock)
    by_section: Counter = Counter()
    all_sections: Counter = Counter()
    current_rows = selected_rows = mismatch = 0
    selected = {"top_daily", "value", "ace", "ace_winner", "double_faults", "sets", "games"}
    for row in archived:
        if not isinstance(row, dict):
            continue
        scheduled = _time(row.get("scheduled_at") or row.get("date"))
        if scheduled is None:
            continue
        for publication in row.get("market_publications") or []:
            if not isinstance(publication, dict):
                continue
            result = publication.get("result")
            if not isinstance(result, dict) or (
                result.get("correct") not in (True, False) and not result.get("void")
            ):
                continue
            market = str(publication.get("market") or "").lower()
            section = {
                "aces": "ace", "most_aces": "ace_winner", "double_faults": "double_faults",
                "sets": "sets", "games": "games",
            }.get(market, str(publication.get("section") or "").lower())
            if not section:
                continue
            all_sections[section] += 1
            if day_key(scheduled) != current_day:
                continue
            issued_snapshot = publication.get("issued_snapshot")
            issued_snapshot = issued_snapshot if isinstance(issued_snapshot, dict) else {}
            betting = row.get("betting")
            betting = betting if isinstance(betting, dict) else {}
            explicit = str(
                publication.get("betting_day")
                or issued_snapshot.get("betting_day")
                or row.get("betting_day")
                or betting.get("betting_day")
                or ""
            )
            # Mirrors the current Admin Today filter in web/app.js.
            if explicit and explicit != current_day:
                mismatch += 1
                continue
            current_rows += 1
            by_section[section] += 1
            if section in selected:
                selected_rows += 1
    # Reconcile the durable Azure archive, not just the daily private feed.
    # Share EXACT issuance, prestart time, frozen price and P/L checks with
    # the offline Most Aces audit. This is aggregate-only and read-only.
    from .most_aces_roi_accounting import audit as audit_most_aces
    accounting = audit_most_aces({"results": archived})
    finance_verified = accounting["status"] == "VERIFIED_ACCOUNTING"
    ace_winner_finance = {
        "source": "durable_results_archive",
        "status": accounting["status"],
        "observed_publications": accounting["counts"].get("observed_publications", 0),
        "settled_priced": accounting["settled_priced"],
        "wins": accounting["counts"].get("wins", 0),
        "losses": accounting["counts"].get("losses", 0),
        "counts": accounting["counts"],
        "errors": accounting["errors"],
        # A FAIL or empty settled sample can never be advertised as ROI.
        "roi": accounting["roi"] if finance_verified else None,
        "profit_units": accounting["profit_units"] if finance_verified else None,
        "member_render_verified": False,
        "provider_requests": 0,
    }
    return {
        "betting_day": current_day,
        "ace_winner_finance": ace_winner_finance,
        "persisted_settled_all_time": sum(all_sections.values()),
        "persisted_by_category_all_time": dict(sorted(all_sections.items())),
        "persisted_settled_today": current_rows,
        "persisted_by_category_today": dict(sorted(by_section.items())),
        "persisted_selected_today": selected_rows,
        "excluded_betting_day_mismatch": mismatch,
        "selected_categories": sorted(selected),
    }


_ACES_OU_CUTOVER = datetime(2026, 11, 1, 5, tzinfo=timezone.utc)


def _verified_aces_outcome(publication: dict) -> dict | None:
    """Read-side repair of verified player O/U results; never rewrite issuer evidence.

    After the Aces O/U cutover a completed Aces result without the exact issued
    player-total contract and actual player count is not a verifiable win/loss.
    Historical pre-cutover records are preserved without reinterpretation.
    """
    pub = deepcopy(publication)
    if str(pub.get("market") or "").lower() != "aces":
        return pub
    issued = _time(pub.get("issued_at"))
    if issued is not None and issued < _ACES_OU_CUTOVER:
        return pub
    result = pub.get("result")
    if not isinstance(result, dict):
        return pub
    if str(pub.get("price_contract") or "").lower() != "player_total_ou":
        return None
    side = str(pub.get("ou_side") or "").lower()
    if side not in {"over", "under"}:
        return None
    try:
        line = float(pub.get("market_line"))
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(line) or line < 0:
        return None
    if result.get("void") is True and str(result.get("reason") or "").lower() in {"retired", "void", "walkover"}:
        return pub
    try:
        raw_actual = result.get("actual_count")
        if isinstance(raw_actual, bool) or raw_actual is None:
            return None
        actual = float(raw_actual)
    except (TypeError, ValueError, OverflowError):
        return None
    if not math.isfinite(actual) or actual < 0:
        return None
    is_push = actual == line
    expected = None if is_push else (actual > line if side == "over" else actual < line)
    if result.get("correct") is expected and bool(result.get("void")) == is_push:
        return pub
    # A stored, verified actual count takes precedence over an obsolete status.
    # This is a serving-only derived view. The original settlement remains in
    # the immutable release/archive for subsequent audited reconciliation.
    revised = dict(result)
    revised.update(status="void" if is_push else "hit" if expected else "miss",
                   correct=expected, void=is_push,
                   ou_readback_regraded=True)
    for field in ("staked_units", "return_units", "profit_units"):
        revised.pop(field, None)
    if is_push:
        revised.update(staked_units=0.0, return_units=0.0, profit_units=0.0)
    elif str(pub.get("price_status") or "").lower() == "priced_projection":
        try:
            odds = float(pub.get("odds"))
        except (TypeError, ValueError, OverflowError):
            odds = float("nan")
        if math.isfinite(odds) and odds > 1:
            revised.update(staked_units=1.0,
                           return_units=odds if expected else 0.0,
                           profit_units=odds-1.0 if expected else -1.0)
    pub["result"] = revised
    return pub


def _verified_original_winner_day(canonical_row: dict, archived_row: dict,
                                  canonical_pub: dict, archived_pub: dict) -> str | None:
    """Repair only an exact historical winner's *read-time* day classification.

    A canonical legacy row may have a different explicit betting_day from its
    verified, pre-match issued archive counterpart. Never rewrite either source
    or move other markets, and never override a disagreeing identity/result.
    """
    if (not isinstance(canonical_row, dict) or not isinstance(archived_row, dict)
            or not isinstance(canonical_pub, dict) or not isinstance(archived_pub, dict)
            or len(canonical_row.get("market_publications") or []) != 1):
        return None
    if (str(archived_pub.get("section") or "").lower() not in {"top_daily", "value"}
            or str(archived_pub.get("market") or "").lower() != "match_winner"
            or str(canonical_pub.get("market") or "match_winner").lower() != "match_winner"
            or str(canonical_pub.get("publication_status") or "published").lower() != "published"
            or str(archived_pub.get("publication_status") or "published").lower() != "published"):
        return None
    proven = archived_pub.get("result")
    if (not isinstance(proven, dict) or proven.get("runtime_source") != "match_status_snapshot"
            or (type(proven.get("correct")) is not bool and proven.get("void") is not True)):
        return None
    prior = canonical_pub.get("result")
    prior = prior if isinstance(prior, dict) else {}
    if (type(prior.get("correct")) is bool
            and prior["correct"] is not proven.get("correct")):
        return None
    if prior.get("void") is True and proven.get("void") is not True:
        return None
    original_start = _time(archived_row.get("scheduled_at") or archived_row.get("date"))
    current_start = _time(canonical_row.get("scheduled_at") or canonical_row.get("date"))
    if original_start is None or current_start is None:
        return None
    if original_start != current_start:
        # A postponed match may retain its *original issued betting day* even
        # though a later feed revision moved the provider's start timestamp.
        # Trust that older day only with an explicit frozen pre-match issue
        # timestamp on BOTH copies. An inferred/legacy issue date, a changed
        # issue timestamp, or a move to an earlier kickoff fails closed.
        original_issued = _time(archived_pub.get("issued_at"))
        current_issued = _time(canonical_pub.get("issued_at"))
        if (original_issued is None or current_issued is None
                or original_issued != current_issued
                or original_issued > original_start
                or original_start > current_start):
            return None
    if str(canonical_row.get("event_id") or canonical_row.get("id") or "") != str(
            archived_row.get("event_id") or archived_row.get("id") or ""):
        return None
    for side in ("player1", "player2"):
        old = archived_row.get(side) or {}
        new = canonical_row.get(side) or {}
        if (not isinstance(old, dict) or not isinstance(new, dict)
                or not old.get("id") or str(old.get("id")) != str(new.get("id") or "")):
            return None
    for field in ("publication_key", "selection_id", "issued_at", "odds"):
        before, after = canonical_pub.get(field), archived_pub.get(field)
        if before not in (None, "") and after not in (None, "") and str(before) != str(after):
            return None

    from .feed import _betting_day_key, _row_betting_day
    authoritative_day = _betting_day_key(original_start)
    if _row_betting_day(archived_row) != authoritative_day:
        return None
    if _row_betting_day(canonical_row) == authoritative_day:
        return None
    return authoritative_day


def merge_settled_results(feed: dict, archived: list[dict]) -> dict:
    """Overlay settled outcomes only, preserving canonical publication metadata."""
    out = dict(feed)
    rows = []
    for source_row in feed.get("results") or []:
        if not isinstance(source_row, dict):
            rows.append(deepcopy(source_row))
            continue
        copy = deepcopy(source_row)
        # Preserve legacy rows without publications; quarantine only invalid
        # Aces results, never unrelated result rows during a readback repair.
        if not isinstance(copy.get("market_publications"), list) or not copy["market_publications"]:
            rows.append(copy)
            continue
        copy["market_publications"] = [validated for pub in copy.get("market_publications") or []
                                        if isinstance(pub, dict)
                                        for validated in [_verified_aces_outcome(pub)]
                                        if validated is not None]
        if copy["market_publications"]:
            rows.append(copy)
    existing = {}
    existing_rows = {}
    identity_counts = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        for publication in row.get("market_publications") or []:
            if not isinstance(publication, dict):
                continue
            key = _identity(row, publication)
            if key:
                existing[key] = publication
                existing_rows[key] = row
                identity_counts[key] = identity_counts.get(key, 0) + 1
    for archived_row in archived:
        if not isinstance(archived_row, dict):
            continue
        pubs = archived_row.get("market_publications") or []
        if len(pubs) != 1 or not isinstance(pubs[0], dict):
            continue
        archived_pub = _verified_aces_outcome(pubs[0])
        if archived_pub is None:
            continue
        key = _identity(archived_row, archived_pub)
        if not key:
            continue
        if key in existing:
            incumbent = existing[key]
            # Use the verified original booking day only for an unambiguous
            # exact published winner with same event, sides, time and price.
            if identity_counts.get(key) == 1:
                canonical_row = existing_rows[key]
                corrected_day = _verified_original_winner_day(
                    canonical_row, archived_row, incumbent, archived_pub,
                )
                if corrected_day:
                    canonical_row["betting_day"] = corrected_day
            previous = incumbent.get("result")
            previous = previous if isinstance(previous, dict) else {}
            updated_result = archived_pub.get("result")
            updated_result = updated_result if isinstance(updated_result, dict) else {}
            # A prior retirement VOID can be superseded only by a freshly
            # verified, irrevocably decided player Aces O/U. Other Results and
            # historical records retain their existing precedence.
            if (
                str(archived_pub.get("market") or "").lower() == "aces"
                and previous.get("void") is True
                and str(previous.get("reason") or previous.get("status") or "").lower()
                    in {"retired", "retirement"}
                and updated_result.get("retirement_line_decided") is True
                and type(updated_result.get("correct")) is bool
            ):
                incumbent["result"] = deepcopy(updated_result)
            elif previous.get("correct") is None and not previous.get("void"):
                incumbent["result"] = deepcopy(archived_pub.get("result"))
            elif (
                # Legacy ACES websites may retain an unverified W/L while the
                # exact original issued bet already has durable provider proof.
                # Upgrade only the read-time result provenance, never quote,
                # statistical projection, threshold, issuer or archive rows.
                str(archived_pub.get("market") or "").lower() == "aces"
                and updated_result.get("runtime_source") == "match_status_snapshot"
                and previous.get("runtime_source") != "match_status_snapshot"
                and (type(previous.get("correct")) is bool or previous.get("void") is True)
                and previous.get("correct") is updated_result.get("correct")
                and bool(previous.get("void")) == bool(updated_result.get("void"))
                and (previous.get("actual_count") is None
                     or previous.get("actual_count") == updated_result.get("actual_count"))
                and all(
                    incumbent.get(field) == archived_pub.get(field)
                    for field in ("publication_key", "selection_id",
                                  "market_line", "ou_side", "odds",
                                  "price_contract", "price_basis", "issued_at")
                )
                and bool(str(incumbent.get("publication_key") or "").strip())
                and incumbent.get("market_line") is not None
                and str(incumbent.get("ou_side") or "").lower() in {"over", "under"}
            ):
                incumbent["result"] = deepcopy(updated_result)
            elif (
                str(archived_pub.get("market") or "match_winner").lower() == "match_winner"
                and updated_result.get("runtime_source") == "match_status_snapshot"
                and previous.get("runtime_source") != "match_status_snapshot"
                and type(previous.get("correct")) is bool
                and previous.get("correct") is updated_result.get("correct")
                and bool(previous.get("void")) == bool(updated_result.get("void"))
                and all(
                    incumbent.get(field) in (None, "")
                    or archived_pub.get(field) in (None, "")
                    or str(incumbent.get(field)) == str(archived_pub.get(field))
                    for field in ("publication_key", "issued_at", "odds")
                )
            ):
                # A legacy feed may contain the correct terminal winner but
                # not the source-native verification marker. Upgrade only the
                # same original market, same outcome and unaltered quote.
                # Conflicting results must stay visible to the parity audit.
                incumbent["result"] = deepcopy(updated_result)
                for field in ("publication_key", "issued_at", "odds"):
                    if incumbent.get(field) in (None, "") and archived_pub.get(field) not in (None, ""):
                        incumbent[field] = deepcopy(archived_pub[field])
            continue
        copy = deepcopy(archived_row)
        copy["market_publications"] = [archived_pub]
        rows.append(copy)
        existing[key] = archived_pub
    rows.sort(key=lambda row: _time(row.get("scheduled_at") or row.get("date")) or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    out["results"] = rows
    return out
