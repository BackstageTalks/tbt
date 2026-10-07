from __future__ import annotations

import argparse
import json
import math
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from _bootstrap import ROOT
from morning_clock import morning_selection_now, morning_publication_delay
from download_tennis_history import read_json, write_json
from history_download_budget import LocalRequestBudget, reserve_allocation
from release_store import ReleaseStore
from tbt.config import settings
from tbt.errors import ProviderError
from tbt.data.history_snapshot import (
    load_partitions,
    sync_year_partition,
    _provider_event_id,
)
from tbt.data.history_safety import sanitize_history_identities, merge_trusted_history_batch
from tbt.data.atp_leaderboards import ATPLeaderboardPriors
from tbt.data.wta_season_stats import WTASeasonPriors
from tbt.models.artifact import load_model, save_model
from tbt.providers.rapidapi import RapidTennisClient
from tbt.providers.budget import RequestBudgetExceeded
from tbt.providers.statistics import NoSupportedStatisticsError, parse_statistics
from tbt.services.engine import predict, reconcile_ledger, serving_feed
from tbt.services.publication import (
    validate_market_publication_candidate,
    restore_published_market_snapshots,
    carry_forward_betting_day_market_rows,
    build_daily_offer_snapshot,
    validate_publication_candidate,
)
from tbt.services.ace_selection import select_ace_picks
from tbt.services.sg_selection import select_sg_picks
from tbt.services.projection_odds import (
    enrich_projection_odds, prefetch_projection_market_board,
    extract_match_total_odds,
)
from tbt.services.indicative_odds import annotate_feed_indicative_odds
from tbt.services.propline_live import PropLineClient, discover_propline_fallback
from tbt.services.doubles_selection import (
    build_predictions as build_doubles_predictions,
    select_picks as select_doubles_picks,
    merge_history as merge_doubles_history,
    history_report as doubles_history_report,
    walk_forward_validation as validate_doubles_history,
)
from tbt.services.comeback_projection import annotate_live_second_set_projections
from tbt.services.market_selection import (
    annotate_market_publication_candidates,
    attach_market_sections_to_feed,
    attach_match_winner_market,
    enrich_current_betting_day_odds,
    extract_match_winner_odds,
)
from tbt.services.training import refit_serving_model, train_from_matches
from tbt.services.backtest_service import walk_forward_backtest
from tbt.services.shadow_evaluation import update_shadow_ledger, build_shadow_report


def clean(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, list):
        return [clean(v) for v in value]
    return value



def _promotion_metric_gate(report):
    """Predeclared probabilistic gate against Elo on the same untouched holdout.

    Lower is better for log loss, Brier and ECE. Accuracy must not regress.
    At least one probabilistic metric must improve strictly.
    """
    holdout = report.get("holdout") or {}
    delta = report.get("delta_vs_elo") or {}

    required = (
        "accuracy",
        "log_loss",
        "brier_score",
        "ece_10",
    )
    if int(holdout.get("n") or 0) < 200:
        return False, ["holdout_n_below_200"]

    missing = [
        key
        for key in required
        if delta.get(key) is None
        or not math.isfinite(float(delta.get(key)))
    ]
    if missing:
        return False, ["missing_or_nonfinite_" + key for key in missing]

    reasons = []
    if float(delta["accuracy"]) < 0.0:
        reasons.append("accuracy_worse_than_elo")
    if float(delta["log_loss"]) > 0.0:
        reasons.append("log_loss_worse_than_elo")
    if float(delta["brier_score"]) > 0.0:
        reasons.append("brier_worse_than_elo")
    if float(delta["ece_10"]) > 0.0:
        reasons.append("ece_worse_than_elo")

    probabilistic_improvement = any(
        float(delta[key]) < 0.0
        for key in (
            "log_loss",
            "brier_score",
            "ece_10",
        )
    )
    if not probabilistic_improvement:
        reasons.append("no_probabilistic_improvement_vs_elo")

    governance = report.get("evaluation_governance") or {}
    if governance.get("eligibility_reason"):
        reasons.append(governance["eligibility_reason"])
    if governance.get("production_present"):
        champion_delta = report.get("delta_vs_production") or {}
        if int((report.get("production_holdout") or {}).get("n") or 0) != int(holdout["n"]):
            reasons.append("production_evaluation_set_mismatch")
        for key in required:
            value = champion_delta.get(key)
            if value is None or not math.isfinite(float(value)):
                reasons.append("missing_production_" + key)
            elif (float(value) < 0 if key == "accuracy" else float(value) > 0):
                reasons.append(key + "_worse_than_production")
        if not any(champion_delta.get(key) is not None and float(champion_delta[key]) < 0
                   for key in ("log_loss", "brier_score", "ece_10")):
            reasons.append("no_probabilistic_improvement_vs_production")

        # ATP and WTA are separate promotion gates. A strong aggregate result
        # must not hide a regression on one tour, which the controlled 2026
        # retraining audit demonstrated can happen.
        candidate_tours = ((report.get("subgroups") or {}).get("tour") or {})
        production_tours = ((report.get("production_subgroups") or {}).get("tour") or {})
        for tour in ("atp", "wta"):
            candidate = candidate_tours.get(tour) or {}
            baseline = production_tours.get(tour) or {}
            candidate_n = int(candidate.get("n") or 0)
            baseline_n = int(baseline.get("n") or 0)
            if candidate_n < 50 or baseline_n != candidate_n:
                reasons.append(f"{tour}_promotion_sample_missing_or_below_50")
                continue
            tour_deltas = {}
            for key in required:
                candidate_value = candidate.get(key)
                baseline_value = baseline.get(key)
                if (
                    candidate_value is None or baseline_value is None
                    or not math.isfinite(float(candidate_value))
                    or not math.isfinite(float(baseline_value))
                ):
                    reasons.append(f"{tour}_missing_or_nonfinite_{key}")
                    continue
                tour_deltas[key] = float(candidate_value) - float(baseline_value)
            if len(tour_deltas) != len(required):
                continue
            if tour_deltas["accuracy"] < 0.0:
                reasons.append(f"{tour}_accuracy_worse_than_production")
            for key in ("log_loss", "brier_score", "ece_10"):
                if tour_deltas[key] > 0.0:
                    reasons.append(f"{tour}_{key}_worse_than_production")
            if not any(tour_deltas[key] < 0.0 for key in ("log_loss", "brier_score", "ece_10")):
                reasons.append(f"{tour}_no_probabilistic_improvement_vs_production")
    return not reasons, reasons


def _promotion_history(path):
    value = read_json(path, [])
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("Invalid promotion history; refusing to forget previous decisions")
    return value


def _holdout_already_used(history, fingerprint):
    return any(
        isinstance(row, dict)
        and row.get("holdout_fingerprint") == fingerprint
        for row in history
    )


def _merge_refresh_batch_safely(matches, incoming, *, day, tour):
    """Quarantine only ambiguous incoming identities; preserve canonical history."""
    merged, accepted, safety = merge_trusted_history_batch(matches, incoming)
    if safety.get("quarantined_rows"):
        print(json.dumps({
            "warning": "ambiguous_match_identity_quarantined",
            "day": day.isoformat(),
            "tour": tour,
            "rows_skipped": safety.get("quarantined_rows"),
            "details": safety.get("rows"),
            "collision": safety.get("collision"),
        }, ensure_ascii=False), flush=True)
    return merged, accepted


def _refresh_history(provider, matches, history_dir, history_store, start, end):
    """Refresh recent completed history without letting one broken old provider day
    take down the whole publication job.

    TennisApi occasionally returns a hard 4xx for one historical calendar date
    while adjacent dates remain healthy. Existing canonical history is
    append/merge-only here, so skipping that *past* day preserves the last known
    good partition and lets the next refresh retry it. The current day remains
    fail-closed because publishing a feed after losing today's discovery would
    be unsafe.
    """
    provider_years = {
        provider_id: match.scheduled_at.astimezone(timezone.utc).year
        for match in matches
        if (provider_id := _provider_event_id(match)) is not None
    }
    skipped_days: set[str] = set()
    # Persist canonical history once per refresh instead of rewriting/uploading
    # the same year after every ATP/WTA calendar response. Keep all provider and
    # identity checks unchanged, collect affected years, then publish one bundle.
    # If a later provider call fails unexpectedly, flush the already-validated
    # earlier rows once before propagating the error so refresh still checkpoints
    # useful work without N repeated rewrites of the same partition.
    affected_years: set[int] = set()

    def persist_pending() -> None:
        if not affected_years:
            return
        written = []
        removed = []
        for year in sorted(affected_years):
            path, was_removed = sync_year_partition(matches, history_dir, year)
            if path is not None:
                written.append(path)
            elif was_removed:
                removed.append(f"history-{year}.parquet")
        if written or removed:
            bundle = written + [history_dir / "history_manifest.json"]
            if removed:
                history_store.upload_bundle(bundle, remove_names=removed)
            else:
                history_store.upload_bundle(bundle)
        affected_years.clear()

    day = start
    try:
        while day <= end:
            day_failed = False
            for tour in ("atp", "wta"):
                try:
                    incoming = [
                        match
                        for match in provider.matches_for_day(
                            tour, day, historical=True
                        )
                        if match.is_completed
                    ]
                except ProviderError as exc:
                    # A historical provider hole must not destroy an otherwise valid
                    # refresh. Do not apply this to today: current-day discovery is
                    # required before we are allowed to publish a new betting feed.
                    if day >= end:
                        raise
                    skipped_days.add(day.isoformat())
                    day_failed = True
                    print(json.dumps({
                        "warning": "historical_provider_day_skipped",
                        "day": day.isoformat(),
                        "tour": tour,
                        "reason": str(exc)[:300],
                        "policy": "preserve_existing_history_and_retry_next_refresh",
                    }, ensure_ascii=False), flush=True)
                    break

                matches, accepted_incoming = _merge_refresh_batch_safely(
                    matches, incoming, day=day, tour=tour
                )

                affected_years.update(
                    match.scheduled_at.astimezone(timezone.utc).year
                    for match in accepted_incoming
                )
                for match in accepted_incoming:
                    provider_id = _provider_event_id(match)
                    if provider_id is not None and provider_id in provider_years:
                        affected_years.add(provider_years[provider_id])

                for match in accepted_incoming:
                    provider_id = _provider_event_id(match)
                    if provider_id is not None:
                        provider_years[provider_id] = (
                            match.scheduled_at.astimezone(timezone.utc).year
                        )
            if day_failed:
                # The same calendar discovery powers ATP, WTA and doubles. Avoid
                # spending another request on a date that just returned a provider
                # error in this run.
                pass
            day += timedelta(days=1)
    except Exception:
        persist_pending()
        raise

    persist_pending()
    provider._tbt_skipped_history_days = skipped_days
    return matches




def _load_prediction_ledger(store):
    """Load a complete prior prediction generation, or bootstrap only if absent.

    An entirely empty prediction release is the only bootstrap state. If either
    feed.json or ledger.json exists, both are required and checksum-verified.
    """
    required = {"feed.json", "ledger.json"}
    assets = store._asset_names()
    present = required & assets
    if not present:
        return []
    if present != required:
        missing = sorted(required - present)
        raise FileNotFoundError(
            "Prediction release is incomplete; missing assets: " + ", ".join(missing)
        )
    optional_snapshot = "daily_offer_snapshot.json" if "daily_offer_snapshot.json" in assets else None
    extra_names = ["feed.json", "ledger.json"]
    if optional_snapshot:
        extra_names.append(optional_snapshot)
    store.download(
        extra_names=tuple(extra_names),
        required_names=("feed.json", "ledger.json"),
    )
    ledger = read_json(store.directory / "ledger.json", None)
    feed = read_json(store.directory / "feed.json", None)
    if not isinstance(ledger, list):
        raise ValueError("Invalid prediction ledger")
    validate_publication_candidate(feed, ledger)
    if (feed.get("market_selection") or {}).get("publication_schema") == 1:
        feed = restore_published_market_snapshots(feed, ledger)
        validate_market_publication_candidate(feed, ledger)
    return ledger

DOUBLES_HISTORY_ASSET = "doubles_history.json"
DOUBLES_REPORT_ASSET = "doubles_history_report.json"


def _load_doubles_history(store):
    assets = store._asset_names()
    if DOUBLES_HISTORY_ASSET not in assets:
        return []
    store.download(extra_names=(DOUBLES_HISTORY_ASSET,), required_names=(DOUBLES_HISTORY_ASSET,))
    payload = read_json(store.directory / DOUBLES_HISTORY_ASSET, {})
    rows = payload.get("matches") if isinstance(payload, dict) else []
    return rows if isinstance(rows, list) else []


def _save_doubles_history(store, rows, *, extra_report=None):
    report = {
        **doubles_history_report(rows),
        "validation": validate_doubles_history(rows),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        **(extra_report or {}),
    }
    write_json(store.directory / DOUBLES_HISTORY_ASSET, {
        "schema": 1,
        "generated_at": report["generated_at"],
        "matches": rows,
    })
    write_json(store.directory / DOUBLES_REPORT_ASSET, report)
    store.upload_bundle([store.directory / DOUBLES_HISTORY_ASSET, store.directory / DOUBLES_REPORT_ASSET])
    return report


def _pending_ace_df_settlement_requirements(ledger):
    """Return issued ACES/DF markets that still need a result, keyed by event."""
    required = {}
    for row in ledger if isinstance(ledger, list) else []:
        if not isinstance(row, dict):
            continue
        event_id = str(row.get("event_id") or row.get("id") or row.get("match_id") or "").strip()
        if not event_id:
            continue
        for publication in row.get("market_publications", []) or []:
            if not isinstance(publication, dict) or not publication.get("issued_at"):
                continue
            market = str(publication.get("market") or "").strip().lower()
            if market not in {"aces", "double_faults"}:
                continue
            result = publication.get("result")
            if isinstance(result, dict):
                status = str(result.get("status") or "").strip().lower()
                if status in {"hit", "miss", "void"}:
                    continue
            required.setdefault(event_id, set()).add(market)
    return required


def _ace_df_required_counts_ready(match, markets):
    stats = match.stats if isinstance(getattr(match, "stats", None), dict) else {}
    keys = []
    if "aces" in markets:
        keys.extend(("p1_aces", "p2_aces"))
    if "double_faults" in markets:
        keys.extend(("p1_double_faults", "p2_double_faults"))
    for key in keys:
        try:
            value = float(stats.get(key))
        except (TypeError, ValueError):
            return False
        if not math.isfinite(value) or value < 0:
            return False
    return True


def _enrich_pending_ace_df_settlement_stats(provider, ledger, matches):
    """Fetch post-match counts only for issued ACES/DF bets that cannot settle yet.

    This is deliberately narrow: no board-wide statistics sweep and no relaxed
    publication rules. A provider miss leaves the bet pending for the next run.
    """
    requirements = _pending_ace_df_settlement_requirements(ledger)
    report = {
        "pending_events": len(requirements),
        "pending_aces": sum("aces" in markets for markets in requirements.values()),
        "pending_double_faults": sum("double_faults" in markets for markets in requirements.values()),
        "completed_candidates": 0,
        "already_ready": 0,
        "enriched": 0,
        "partial_or_unavailable": 0,
        "missing_match": 0,
        "missing_provider_event_id": 0,
        "identity_unavailable": 0,
        "errors": 0,
        "budget_stopped": False,
        "requests_used": 0,
    }
    if not requirements:
        return report

    before_requests = int(getattr(provider, "request_count", 0) or 0)
    by_match_id = {
        str(getattr(match, "match_id", "") or ""): match
        for match in matches
        if getattr(match, "match_id", None)
    }

    for event_id, markets in sorted(requirements.items()):
        match = by_match_id.get(event_id)
        if match is None:
            report["missing_match"] += 1
            continue
        if not getattr(match, "is_completed", False):
            continue
        report["completed_candidates"] += 1
        if _ace_df_required_counts_ready(match, markets):
            report["already_ready"] += 1
            continue

        provider_event_id = _provider_event_id(match)
        if provider_event_id is None:
            report["missing_provider_event_id"] += 1
            continue

        try:
            raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
            identity = raw.get("_tbt_event_identity") if isinstance(raw.get("_tbt_event_identity"), dict) else {}
            home = str(identity.get("home") or "")
            away = str(identity.get("away") or "")
            if (
                identity.get("event_id") != str(provider_event_id)
                or identity.get("status") != "finished"
                or {home, away} != {str(match.player1_id), str(match.player2_id)}
                or not home or home == away
            ):
                detail = provider._get(f"/api/tennis/event/{provider_event_id}", enrichment=True)
                event = detail.get("event", detail) if isinstance(detail, dict) else {}
                home = str((event.get("homeTeam") or {}).get("id") or "")
                away = str((event.get("awayTeam") or {}).get("id") or "")
                if (
                    str((event.get("status") or {}).get("type") or "") != "finished"
                    or {home, away} != {str(match.player1_id), str(match.player2_id)}
                    or not home or home == away
                ):
                    report["identity_unavailable"] += 1
                    continue

            payload = provider.event_statistics(provider_event_id)
            stats = parse_statistics(payload, home_is_player1=home == str(match.player1_id))
            match.stats = {**(match.stats if isinstance(match.stats, dict) else {}), **stats}
            if _ace_df_required_counts_ready(match, markets):
                report["enriched"] += 1
            else:
                report["partial_or_unavailable"] += 1
        except NoSupportedStatisticsError:
            report["partial_or_unavailable"] += 1
        except RequestBudgetExceeded:
            report["budget_stopped"] = True
            break
        except ProviderError as exc:
            report["errors"] += 1
            if report["errors"] <= 5:
                print(json.dumps({
                    "warning": "ace_df_settlement_statistics_error",
                    "event_id": event_id,
                    "provider_event_id": str(provider_event_id),
                    "reason": str(exc)[:300],
                }, ensure_ascii=False), flush=True)

    report["requests_used"] = max(
        0, int(getattr(provider, "request_count", 0) or 0) - before_requests
    )
    return report


def _projection_presentation_integrity(feed, *, ace_picks=None, sg_picks=None,
                                       quarantined=None):
    expected = {
        "aces": sum(1 for row in (ace_picks or []) if str(row.get("market") or "").lower() == "aces"),
        "double_faults": sum(1 for row in (ace_picks or []) if str(row.get("market") or "").lower() == "double_faults"),
        "sets": sum(1 for row in (sg_picks or []) if str(row.get("market") or "").lower() == "sets"),
        "games": sum(1 for row in (sg_picks or []) if str(row.get("market") or "").lower() == "games"),
    }
    actual = {
        "aces": sum(1 for row in (feed.get("ace_picks") or []) if str(row.get("market") or "").lower() == "aces"),
        "double_faults": sum(1 for row in (feed.get("ace_picks") or []) if str(row.get("market") or "").lower() == "double_faults"),
        "sets": sum(1 for row in (feed.get("sg_picks") or []) if str(row.get("market") or "").lower() == "sets"),
        "games": sum(1 for row in (feed.get("sg_picks") or []) if str(row.get("market") or "").lower() == "games"),
    }
    # Only restore_published_market_snapshots may suppress a projection:
    # it first checks the immutable ledger and drops ambiguous/legacy snapshots
    # individually. An unaccounted loss still aborts the entire deployment.
    quarantined = list(quarantined or [])
    withheld = {market: sum(item.get("market") == market for item in quarantined)
                for market in expected}
    mismatches = {
        market: {
            "selected": expected[market], "published": actual[market],
            "ledger_quarantined": withheld[market],
        }
        for market in expected
        if expected[market] != actual[market] + withheld[market]
    }
    report = {
        "ok": not mismatches, "selected": expected, "published": actual,
        "ledger_quarantined": withheld, "quarantine_details": quarantined,
        "mismatches": mismatches,
    }
    if mismatches:
        raise RuntimeError(
            "Projection presentation integrity failure: unexplained selector output loss: "
            + json.dumps(mismatches, sort_keys=True)
        )
    return report


def _publish_predictions(
    store, ledger, predictions, matches, model, report, upcoming,
    *, odds_report=None, ace_picks=None, ace_report=None,
    sg_picks=None, sg_report=None, doubles_picks=None, doubles_report=None,
    doubles_matches=None, doubles_upcoming=None, prior_feed=None, prior_snapshot=None,
    settlement_matches=None,
    betting_day_start_hour=6, morning_refresh=False,
):
    # This stage publishes a pending deployment candidate. `issued_at` stays
    # empty until the workflow confirms a successful public Azure deployment.
    now = datetime.now(timezone.utc)
    # Betting sections have their own publication lifecycle. The Match Winner
    # probability may already be public before provider odds arrive, so freeze
    # pending Daily / Prime / Value candidates independently and confirm them only
    # after the exact feed is deployed.
    ledger_predictions = list(predictions) + list(doubles_picks or [])
    ledger_predictions = annotate_market_publication_candidates(
        ledger_predictions, ace_picks=ace_picks, sg_picks=sg_picks, doubles_picks=doubles_picks
    )
    settlement_source = matches if settlement_matches is None else settlement_matches
    settlement_rows = list(settlement_source) + list(doubles_matches or [])
    records = reconcile_ledger(ledger, ledger_predictions, settlement_rows, now)
    feed_upcoming = list(upcoming) + list(doubles_upcoming or [])
    feed = serving_feed(records, model, matches, report, feed_upcoming, now)
    # Market presentation fields are derived from current odds-backed predictions
    # and never alter the immutable Match Winner probability commitment.
    feed = attach_market_sections_to_feed(
        feed, ledger_predictions, odds_report=odds_report,
        ace_picks=ace_picks, ace_report=ace_report,
        sg_picks=sg_picks, sg_report=sg_report,
        doubles_picks=doubles_picks, doubles_report=doubles_report,
    )
    # PRIME remains internal, but its rows carry a separately trained-on-history
    # conditional projection used only after the favourite loses set 1 LIVE.
    feed, comeback_report = annotate_live_second_set_projections(feed, matches, now=now)
    feed["market_selection"] = {
        **(feed.get("market_selection") or {}),
        "live_second_set_projection_report": comeback_report,
    }
    # First validate/restore the *current selector output* before daily carry-forward.
    # The selector integrity contract is exact only at this stage: after the
    # betting-day snapshot is merged, the final public feed is intentionally a
    # superset because already-issued morning rows remain visible after start.
    feed = clean(feed)
    projection_quarantine = []
    feed = restore_published_market_snapshots(
        feed, records, quarantine_report=projection_quarantine,
    )
    integrity = _projection_presentation_integrity(
        feed, ace_picks=ace_picks, sg_picks=sg_picks,
        quarantined=projection_quarantine,
    )
    if projection_quarantine:
        print(json.dumps({"projection_publication_quarantine": integrity},
                         sort_keys=True), flush=True)
    feed["market_selection"] = {
        **(feed.get("market_selection") or {}),
        "presentation_integrity": integrity,
    }

    # r55 daily offer snapshot: once an exact market row has been successfully
    # deployed/issued during the current BlinQ betting day, keep that immutable
    # row in the public offer even after its event starts. Newly qualifying rows
    # may append, but the morning offer never shrinks or reorders underneath a
    # ROOKIE/PRO user. Do this only after current-selector integrity succeeds;
    # carried rows are expected to make final section counts larger than the
    # current selector counts.
    snapshot_sources = []
    if isinstance(prior_snapshot, dict) and prior_snapshot:
        snapshot_sources.append(prior_snapshot)
    if isinstance(prior_feed, dict) and prior_feed:
        snapshot_sources.append(prior_feed)
    if snapshot_sources or morning_refresh:
        feed, daily_snapshot_report = carry_forward_betting_day_market_rows(
            feed,
            snapshot_sources,
            records,
            now=now,
            start_hour=betting_day_start_hour,
        )
        feed["market_selection"] = {
            **(feed.get("market_selection") or {}),
            "daily_offer_snapshot": daily_snapshot_report,
        }

    feed = clean(feed)
    validate_publication_candidate(feed, records)
    validate_market_publication_candidate(feed, records)
    snapshot = build_daily_offer_snapshot(
        feed,
        now=now,
        start_hour=betting_day_start_hour,
    )
    # Decorate only the serving feed, after all immutable issuance checks.
    # Historical ledger, snapshots and REAL betting ROI stay untouched.
    feed, indicative_audit = annotate_feed_indicative_odds(feed)
    feed["indicative_odds_audit"] = indicative_audit
    write_json(store.directory / "ledger.json", records)
    write_json(store.directory / "feed.json", feed)
    write_json(store.directory / "daily_offer_snapshot.json", snapshot)
    store.upload_bundle([
        store.directory / "ledger.json",
        store.directory / "feed.json",
        store.directory / "daily_offer_snapshot.json",
    ])
    return feed


def main():
    parser = argparse.ArgumentParser(description="Offline BlinQ training and prediction publication")
    parser.add_argument("mode", choices=["train", "refresh", "current-refresh", "backtest"])
    parser.add_argument("--data-repository", default=os.getenv("TBT_DATA_REPOSITORY", "BackstageTalks/tbt-data"))
    parser.add_argument("--max-requests", type=int, default=750)
    parser.add_argument(
        "--market-odds-max-events",
        type=int,
        default=150,
        help="Maximum provider-1 odds calls for the current BlinQ betting day",
    )
    parser.add_argument(
        "--propline-max-events", type=int, default=75,
        help="Max PropLine fallback events per refresh (0 disables, max 75)",
    )
    parser.add_argument(
        "--doubles-odds-max-events",
        type=int,
        default=40,
        help="Maximum provider-1 Match Winner odds calls for isolated doubles candidates",
    )
    parser.add_argument(
        "--betting-day-start-hour",
        type=int,
        default=6,
        help="Europe/Bratislava local hour that starts the BlinQ betting day",
    )
    parser.add_argument(
        "--morning-refresh", action="store_true",
        help="Prepare the upcoming local betting day before 06:00 and wait until 06:01 to publish",
    )
    parser.add_argument("--promote", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.max_requests <= 3000:
        parser.error("refresh allowance must be 1..3000")
    if args.market_odds_max_events < 0:
        parser.error("market-odds-max-events must be >= 0")
    if not 0 <= args.propline_max_events <= 75:
        parser.error("propline-max-events must be 0..75")
    if args.doubles_odds_max_events < 0:
        parser.error("doubles-odds-max-events must be >= 0")
    if not 0 <= args.betting_day_start_hour <= 23:
        parser.error("betting-day-start-hour must be 0..23")
    cache = ROOT / ".cache/tbt"
    history_dir = cache / "history"
    history_store = ReleaseStore(args.data_repository, "tbt-data-v1", history_dir)
    history_store.download()
    matches = load_partitions(history_dir)
    matches, history_safety = sanitize_history_identities(matches)
    if history_safety.get("changed"):
        print(json.dumps({"history_safety": history_safety}, ensure_ascii=False), flush=True)

    atp_leaderboards = None
    if args.mode in {"train", "backtest", "refresh", "current-refresh"}:
        atp_dir = cache / "atp-leaderboards"
        atp_asset = "atp_leaderboards_1991_2026_52week_career.csv"
        try:
            atp_store = ReleaseStore(
                args.data_repository,
                "tbt-atp-leaderboards-v1",
                atp_dir,
            )
            assets = atp_store._asset_names()
            if atp_asset in assets:
                atp_store.download(
                    extra_names=(atp_asset,),
                    required_names=(atp_asset,),
                    require_bundle_manifest=True,
                )
                atp_leaderboards = ATPLeaderboardPriors.from_csv(
                    atp_dir / atp_asset
                )
                print(json.dumps({
                    "atp_leaderboards": {
                        "status": "loaded",
                        "asset": atp_asset,
                        "historical_policy": "previous_completed_season_only",
                        "current_policy": "rolling_52week",
                    }
                }, ensure_ascii=False), flush=True)
            else:
                print(json.dumps({
                    "warning": "atp_leaderboards_release_missing_asset",
                    "asset": atp_asset,
                }), flush=True)
        except Exception as exc:
            print(json.dumps({
                "warning": "atp_leaderboards_unavailable",
                "reason": str(exc)[:300],
            }), flush=True)
    wta_season_stats = None
    if args.mode in {"train", "backtest", "refresh", "current-refresh"}:
        wta_dir = cache / "wta-season-stats"
        wta_asset = "wta_stats_2010_2026_serving_returning.csv"
        try:
            wta_store = ReleaseStore(
                args.data_repository,
                "tbt-wta-season-stats-v1",
                wta_dir,
            )
            wta_assets = wta_store._asset_names()
            if wta_asset in wta_assets:
                wta_store.download(
                    extra_names=(wta_asset,),
                    required_names=(wta_asset,),
                    require_bundle_manifest=True,
                )
                wta_season_stats = WTASeasonPriors.from_csv(wta_dir / wta_asset)
                print(json.dumps({
                    "wta_season_stats": {
                        "status": "loaded",
                        "asset": wta_asset,
                        "historical_policy": "previous_completed_season_only",
                        "current_policy": "previous_completed_season_only",
                    }
                }, ensure_ascii=False), flush=True)
            else:
                print(json.dumps({
                    "warning": "wta_season_stats_release_missing_asset",
                    "asset": wta_asset,
                }), flush=True)
        except Exception as exc:
            print(json.dumps({
                "warning": "wta_season_stats_unavailable",
                "reason": str(exc)[:300],
            }), flush=True)

    model_dir = cache / "model"
    if args.mode == "backtest":
        report = clean(walk_forward_backtest(
            matches, atp_leaderboards=atp_leaderboards,
            wta_season_stats=wta_season_stats
        ))
        path = cache / "backtest.json"
        write_json(path, report)
        store = ReleaseStore(args.data_repository, "tbt-reports-v1", cache / "reports")
        store.upload([path])
        print(json.dumps(report.get("overall", report.get("metrics", {})), indent=2))
        return
    if args.mode == "train":
        candidate = ReleaseStore(args.data_repository, "tbt-model-candidate-v1", model_dir)
        candidate_assets = candidate._asset_names()
        candidate.download(
            extra_names=("promotion_history.json",),
            required_names=("promotion_history.json",) if "promotion_history.json" in candidate_assets else (),
        )
        promotion_history_path = model_dir / "promotion_history.json"
        promotion_history = (_promotion_history(promotion_history_path)
                             if "promotion_history.json" in candidate_assets else [])
        production_dir = cache / "production"
        production = ReleaseStore(args.data_repository, "tbt-model-production-v1", production_dir)
        production_assets = production._asset_names()
        champion = None
        if production_assets:
            production.download(
                extra_names=("model.joblib", "training_report.json", "promotion_history.json"),
                required_names=("model.joblib", "training_report.json") +
                    (("promotion_history.json",) if "promotion_history.json" in production_assets else ()),
            )
            champion = load_model(str(production_dir / "model.joblib"))
            for decision in (_promotion_history(production_dir / "promotion_history.json")
                             if "promotion_history.json" in production_assets else []):
                if decision not in promotion_history:
                    promotion_history.append(decision)
        result = train_from_matches(
            matches,
            production_model=champion,
            promotion_history=promotion_history,
            atp_leaderboards=atp_leaderboards,
            wta_season_stats=wta_season_stats,
        )
        report = clean(result.report)
        governance = report.get("evaluation_governance") or {}
        fingerprint = str(governance.get("holdout_fingerprint") or "")
        eligibility_reason = governance.get("eligibility_reason")
        deferred = eligibility_reason == "no_eligible_unseen_evaluation_rows"

        if deferred:
            # This is not a model/data failure. The candidate is reproducibly
            # trainable, but production promotion must wait for later matches
            # that neither the champion nor an earlier promotion decision saw.
            eligible = False
            gate_reasons = [eligibility_reason]
        else:
            eligible, gate_reasons = _promotion_metric_gate(report)
            if not fingerprint:
                eligible = False
                gate_reasons.append("missing_holdout_fingerprint")
            elif _holdout_already_used(promotion_history, fingerprint):
                eligible = False
                gate_reasons.append("reused_holdout_fingerprint")

        if not args.promote:
            decision_status = "not_requested"
        elif deferred:
            decision_status = "deferred"
        elif eligible:
            decision_status = "approved"
        else:
            decision_status = "rejected"

        decision = {
            "holdout_fingerprint": fingerprint,
            "candidate_version": result.model.version,
            "production_version": getattr(champion, "version", None),
            "decided_at": datetime.now(timezone.utc).isoformat(),
            "reference": governance.get("promotion_reference"),
            "holdout_period": (report.get("periods") or {}).get("holdout"),
            "holdout_metrics": report.get("holdout"),
            "production_metrics": report.get("production_holdout"),
            "delta_vs_elo": report.get("delta_vs_elo"),
            "delta_vs_production": report.get("delta_vs_production"),
            "eligible": eligible,
            "promotion_requested": args.promote,
            "decision": decision_status,
            "reasons": gate_reasons,
        }
        model_to_save = result.model
        if args.promote and eligible:
            # The untouched holdout has finished its only governance job. Build
            # a fresh serving artifact that consumes all outcomes through the
            # evaluated period while freezing the selected blend/calibrator type.
            model_to_save = refit_serving_model(result)
            decision["serving_version"] = model_to_save.version
            decision["serving_history_end"] = model_to_save.metadata.get("history_end")
            report["serving_refit"] = {
                "enabled": True,
                "selection_model_version": result.model.version,
                "serving_model_version": model_to_save.version,
                "selection_evaluation_end": result.model.metadata.get("evaluation_end"),
                "serving_history_end": model_to_save.metadata.get("history_end"),
                "production_train_matches": model_to_save.metadata.get("production_train_matches"),
                "production_calibration_matches": model_to_save.metadata.get(
                    "production_calibration_matches"
                ),
                "blend_weight_boost": model_to_save.blend_weight,
                "elo_weight": getattr(model_to_save, "elo_weight", 0.0),
                "calibration_method": model_to_save.calibrator.kind,
            }

        # Only a real evaluated holdout is consumable governance evidence.
        # Deferred attempts carry no fingerprint and therefore must not poison
        # future unseen evaluation windows.
        if fingerprint:
            promotion_history.append(decision)

        # Keep the current attempt visible even when it is deferred and thus is
        # intentionally absent from promotion_history.
        report["promotion_decision"] = decision
        save_model(model_to_save, str(model_dir / "model.joblib"))
        write_json(model_dir / "training_report.json", report)
        write_json(promotion_history_path, promotion_history)
        candidate.upload_bundle([model_dir / "model.joblib", model_dir / "training_report.json",
                                 promotion_history_path])
        print(json.dumps(decision, indent=2))
        if args.promote:
            if deferred:
                print(
                    "Candidate saved. Promotion deferred until new unseen evaluation rows exist; "
                    "current champion unchanged.",
                    flush=True,
                )
                return
            if not eligible:
                raise SystemExit("Candidate saved. Promotion refused by governance gate; current champion unchanged.")
            production.upload_bundle([model_dir / "model.joblib", model_dir / "training_report.json",
                                      promotion_history_path])
        return
    if not settings.rapidapi_key:
        parser.error("RAPIDAPI_KEY is required")
    model_store = ReleaseStore(args.data_repository, "tbt-model-production-v1", model_dir)
    model_store.download(
        extra_names=("model.joblib", "training_report.json"),
        required_names=("model.joblib", "training_report.json"),
    )
    model = load_model(str(model_dir / "model.joblib"))
    report = read_json(model_dir / "training_report.json", {})

    # Private challenger shadow evaluation. This never mutates the public feed
    # and never consumes Tennis provider requests. A broken/missing shadow
    # artifact must not block the production refresh.
    challenger_model = None
    challenger_version = ""
    shadow_dir = cache / "shadow"
    shadow_store = None
    shadow_ledger = []
    shadow_report = {}
    shadow_enabled = False
    try:
        candidate_dir = cache / "candidate-shadow"
        candidate_store = ReleaseStore(
            args.data_repository, "tbt-model-candidate-v1", candidate_dir
        )
        candidate_assets = candidate_store._asset_names()
        if "model.joblib" in candidate_assets:
            candidate_store.download(
                extra_names=("model.joblib",),
                required_names=("model.joblib",),
            )
            challenger_model = load_model(str(candidate_dir / "model.joblib"))
            challenger_version = str(getattr(challenger_model, "version", "") or "")

        shadow_store = ReleaseStore(
            args.data_repository, "tbt-model-shadow-v1", shadow_dir
        )
        shadow_assets = shadow_store._asset_names()
        shadow_required = {"shadow_ledger.json", "shadow_report.json"}
        if shadow_required <= shadow_assets:
            shadow_store.download(
                extra_names=tuple(sorted(shadow_required)),
                required_names=tuple(sorted(shadow_required)),
            )
            prior_shadow = read_json(shadow_dir / "shadow_ledger.json", [])
            if not isinstance(prior_shadow, list):
                raise ValueError("Invalid shadow ledger")
            shadow_ledger = prior_shadow
        elif shadow_assets & shadow_required:
            raise FileNotFoundError("Incomplete private shadow evaluation release")
        elif not shadow_assets:
            # Bootstrap the private shadow release immediately.  A later provider
            # failure (for example shared-budget exhaustion) must never leave a
            # created release with no ledger/report assets.
            initial_report = build_shadow_report(
                [],
                production_model_version=str(getattr(model, "version", "") or ""),
                challenger_model_version=challenger_version,
            )
            initial_report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
            initial_report["status"] = "initialized_waiting_for_first_pre_match_snapshot"
            write_json(shadow_dir / "shadow_ledger.json", [])
            write_json(shadow_dir / "shadow_report.json", clean(initial_report))
            shadow_store.upload_bundle([
                shadow_dir / "shadow_ledger.json",
                shadow_dir / "shadow_report.json",
            ])
            shadow_assets = shadow_required

        shadow_enabled = bool(
            challenger_model is not None
            and challenger_version
            and challenger_version != str(getattr(model, "version", "") or "")
        )
    except Exception as exc:
        print(json.dumps({
            "warning": "shadow_evaluation_disabled",
            "detail": str(exc)[:500],
        }, ensure_ascii=False), flush=True)
        challenger_model = None
        challenger_version = ""
        shadow_store = None
        shadow_enabled = False

    prediction_dir = cache / "predictions"
    prediction_store = ReleaseStore(
        args.data_repository,
        "tbt-predictions-v1",
        prediction_dir,
    )
    prediction_ledger = _load_prediction_ledger(prediction_store)
    # _load_prediction_ledger downloads the complete prior release when one
    # exists. Keep the previously deployed candidate as the source of truth for
    # today's already-issued offer rows.
    prior_feed = read_json(prediction_dir / "feed.json", {})
    if not isinstance(prior_feed, dict):
        prior_feed = {}
    prior_snapshot = read_json(prediction_dir / "daily_offer_snapshot.json", {})
    if not isinstance(prior_snapshot, dict):
        prior_snapshot = {}
    doubles_dir = cache / "doubles"
    doubles_store = ReleaseStore(args.data_repository, "tbt-doubles-data-v1", doubles_dir)
    doubles_history = _load_doubles_history(doubles_store)
    current_only = args.mode == "current-refresh"
    budget_path = history_dir / "request_budget.json"
    if current_only:
        # Emergency/current-day serving refresh is deliberately read-only with
        # respect to canonical history. The durable shared API guard remains the
        # hard quota authority; do not mutate the history release just to reserve
        # a local allowance.
        allowance = args.max_requests
    else:
        ledger, allowance = reserve_allocation(read_json(budget_path, {}), args.max_requests,
            run_id=os.getenv("GITHUB_RUN_ID", "manual"), purpose="refresh")
        if not allowance:
            raise SystemExit("Refresh budget exhausted; previously deployed feed stays available with its timestamp")
        write_json(budget_path, ledger)
        history_store.upload_bundle([budget_path])
    budget = LocalRequestBudget(history_dir / "local_request_budget.sqlite", duration_seconds=1800)
    provider = RapidTennisClient(request_budget=budget)
    provider.request_limit = allowance
    now = datetime.now(timezone.utc)
    refresh_error = None
    upcoming = []
    odds_report = None
    ace_picks = []
    ace_report = None
    sg_picks = []
    sg_report = None
    doubles_picks = []
    doubles_report = None
    doubles_completed = []
    ace_df_settlement_stats_report = {}
    doubles_upcoming = []
    try:
        if current_only:
            # Recovery refreshes keep canonical history read-only, but they still
            # need the latest completed matches in memory. Otherwise yesterday's
            # issued picks cannot settle and today's model misses the most recent
            # form. Fetch only yesterday + today and merge safely without writing
            # or publishing history partitions.
            skipped_history_days = set()
            recent_completed = 0
            recent_start = now.date() - timedelta(days=1)
            recent_day = recent_start
            while recent_day <= now.date():
                day_failed = False
                for tour in ("atp", "wta"):
                    try:
                        incoming = [
                            match for match in provider.matches_for_day(
                                tour, recent_day, historical=True
                            )
                            if match.is_completed
                        ]
                    except ProviderError as exc:
                        if recent_day >= now.date():
                            raise
                        skipped_history_days.add(recent_day.isoformat())
                        day_failed = True
                        print(json.dumps({
                            "warning": "current_refresh_recent_day_skipped",
                            "day": recent_day.isoformat(),
                            "tour": tour,
                            "reason": str(exc)[:300],
                        }, ensure_ascii=False), flush=True)
                        break
                    matches, accepted = _merge_refresh_batch_safely(
                        matches, incoming, day=recent_day, tour=tour
                    )
                    recent_completed += len(accepted)
                recent_day += timedelta(days=1)
            print(json.dumps({
                "current_refresh": {
                    "canonical_history": "read_only",
                    "history_matches": len(matches),
                    "recent_completed_refreshed_in_memory": recent_completed,
                    "recent_window_start": recent_start.isoformat(),
                    "recent_window_end": now.date().isoformat(),
                    "window_start": now.date().isoformat(),
                    "window_end": (now.date() + timedelta(days=3)).isoformat(),
                }
            }), flush=True)
        else:
            matches = _refresh_history(
                provider, matches, history_dir, history_store,
                now.date() - timedelta(days=7), now.date()
            )
            skipped_history_days = set(
                getattr(provider, "_tbt_skipped_history_days", set())
            )

        # Settlement has priority over fresh market discovery: fetch whole-match
        # Aces/DF counts only for already-issued, still-pending ACES/DF bets.
        ace_df_settlement_stats_report = _enrich_pending_ace_df_settlement_stats(
            provider, prediction_ledger, matches
        )
        print(json.dumps({
            "ace_df_settlement_statistics": ace_df_settlement_stats_report
        }, ensure_ascii=False), flush=True)
        for tour in ("atp", "wta"):
            upcoming.extend(provider.upcoming(tour, now.date(), now.date() + timedelta(days=3)))

        # Provider calls retain their actual timestamps. Before 06:00, evaluate
        # eligibility against the upcoming local betting day; never backdate.
        selection_now = (
            morning_selection_now(
                datetime.now(timezone.utc), start_hour=args.betting_day_start_hour
            ) if args.morning_refresh else now
        )
        if args.morning_refresh:
            print(json.dumps({"morning_selection_clock": selection_now.isoformat()}), flush=True)

        # Doubles uses a separate pair/member model. The raw daily event calls are
        # already cached by the singles refresh above, so maintaining the recent
        # doubles history adds very little discovery traffic.
        if current_only:
            # Keep the doubles release read-only during recovery, but merge the
            # latest completed matches in memory so Results and today's doubles
            # model do not lag a day behind.
            doubles_day = now.date() - timedelta(days=1)
            while doubles_day <= now.date():
                if doubles_day.isoformat() in skipped_history_days:
                    doubles_day += timedelta(days=1)
                    continue
                try:
                    doubles_completed.extend(
                        match for match in provider.doubles_for_day(
                            doubles_day, historical=True
                        )
                        if match.is_completed
                    )
                except ProviderError:
                    if doubles_day >= now.date():
                        raise
                doubles_day += timedelta(days=1)
            doubles_history = merge_doubles_history(doubles_history, doubles_completed)
            doubles_history_state = {
                "status": "reused_plus_recent_in_memory",
                "matches": len(doubles_history),
                "recent_completed_refreshed": len(doubles_completed),
            }
        else:
            doubles_day = now.date() - timedelta(days=7)
            while doubles_day <= now.date():
                if doubles_day.isoformat() in skipped_history_days:
                    doubles_day += timedelta(days=1)
                    continue
                doubles_completed.extend(
                    match for match in provider.doubles_for_day(doubles_day, historical=True)
                    if match.is_completed
                )
                doubles_day += timedelta(days=1)
            doubles_history = merge_doubles_history(doubles_history, doubles_completed)
            doubles_history_state = _save_doubles_history(
                doubles_store, doubles_history,
                extra_report={"recent_completed_refreshed": len(doubles_completed)},
            )
        doubles_upcoming = provider.doubles_upcoming(now.date(), now.date() + timedelta(days=3))
        doubles_predictions, doubles_model_report = build_doubles_predictions(
            doubles_history, doubles_upcoming, now=now
        )
        doubles_odds_report = {}
        if args.doubles_odds_max_events and doubles_predictions:
            doubles_predictions, doubles_odds_report = enrich_current_betting_day_odds(
                provider, doubles_predictions, now=selection_now,
                max_events=args.doubles_odds_max_events, provider_id=1,
                timezone_name="Europe/Bratislava", start_hour=args.betting_day_start_hour,
                candidate_min_probability=0.55, candidate_min_data_depth=0.35,
                candidate_min_surface_matches=2,
            )
        doubles_picks, doubles_selection_report = select_doubles_picks(doubles_predictions)
        doubles_report = {
            "history": doubles_history_state,
            "model": doubles_model_report,
            "odds": doubles_odds_report,
            "selection": doubles_selection_report,
        }

        # Odds-first for ACES/DF/GAMES/SETS: obtain actual available offers
        # BEFORE evaluating their projection models. Match Winner continues to
        # use its independent qualification rules and shares cached payloads.
        prediction_now = datetime.now(timezone.utc)
        predictions = predict(
            model, matches, upcoming, now=prediction_now,
            atp_leaderboards=atp_leaderboards,
            wta_season_stats=wta_season_stats,
        )

        # Score the exact same pre-match fixtures with the private challenger.
        # Only the first snapshot for a model-pair/fixture is retained. Results
        # are settled later from canonical completed history.
        if shadow_store is not None:
            challenger_predictions = (
                predict(
                    challenger_model, matches, upcoming, now=prediction_now,
                    atp_leaderboards=atp_leaderboards,
                    wta_season_stats=wta_season_stats,
                )
                if shadow_enabled else []
            )
            shadow_ledger = update_shadow_ledger(
                shadow_ledger,
                production_predictions=predictions,
                challenger_predictions=challenger_predictions,
                completed_matches=matches,
                production_model_version=str(getattr(model, "version", "") or ""),
                challenger_model_version=challenger_version if shadow_enabled else "",
                now=prediction_now,
            )
            if shadow_enabled:
                shadow_report = build_shadow_report(
                    shadow_ledger,
                    production_model_version=str(getattr(model, "version", "") or ""),
                    challenger_model_version=challenger_version,
                )
                shadow_report["generated_at_utc"] = prediction_now.isoformat()
                write_json(shadow_dir / "shadow_ledger.json", shadow_ledger)
                write_json(shadow_dir / "shadow_report.json", clean(shadow_report))
                shadow_store.upload_bundle([
                    shadow_dir / "shadow_ledger.json",
                    shadow_dir / "shadow_report.json",
                ])
                print(json.dumps({
                    "shadow_evaluation": {
                        "production": str(getattr(model, "version", "") or ""),
                        "challenger": challenger_version,
                        "captured": shadow_report.get("cohort", {}).get("captured", 0),
                        "settled": shadow_report.get("cohort", {}).get("settled", 0),
                        "minimum_for_review": shadow_report.get("cohort", {}).get("minimum_for_review", 200),
                        "ready_for_promotion_review": shadow_report.get("gate", {}).get("ready_for_promotion_review", False),
                    }
                }, ensure_ascii=False), flush=True)

        projection_odds_cap = max(0, int(args.market_odds_max_events or 0))
        market_odds_cap = projection_odds_cap
        # current-refresh now uses the same complete market discovery as a normal
        # refresh. The shared provider budget and per-run cap are the safety rails;
        # public market coverage must not be reduced merely to save requests.
        projection_odds_report = {}
        projection_market_cache = {}
        available_projection_markets = {}
        projection_discovery_report = {}
        bookmaker_lines_by_event = {}
        prop_market_payloads = {}
        if projection_odds_cap:
            # Both market discovery and Match Winner share the SAME global
            # RapidAPI limit. Reserve a third of the available quota (up to 40
            # requests) for otherwise-unpriced Match Winner candidates; the
            # prefetch cache already covers overlapping events at zero cost.
            remaining_total = (max(0, int(provider.request_limit) - int(provider.request_count))
                               if provider.request_limit is not None else 2 * projection_odds_cap)
            reserved_match_winner = min(40, remaining_total // 3)
            remaining = max(0, remaining_total - reserved_match_winner)
            available_odds_calls = min(projection_odds_cap, remaining)
            (projection_market_cache, available_projection_markets,
             projection_discovery_report) = prefetch_projection_market_board(
                provider, predictions, now=selection_now, max_events=available_odds_calls,
                provider_id=1,
            )
            projection_discovery_report["remaining_request_budget_at_start"] = remaining_total
            projection_discovery_report["reserved_match_winner_requests"] = reserved_match_winner
            projection_discovery_report["requested_event_cap"] = projection_odds_cap
            for event_id, markets in available_projection_markets.items():
                payload = projection_market_cache.get(event_id)
                bookmaker_lines_by_event[event_id] = {
                    market: [float(quote["line"]) for quote in
                             extract_match_total_odds(payload, market)]
                    for market in ("sets", "games") if market in markets
                }

            # ACES / Double Faults real-odds contract: the legacy RapidAPI
            # prop prices are not trusted for publication. Keep RapidAPI as
            # the primary source for Games/Sets and Match Winner, but require
            # PropLine for current Aces/DF. If PropLine has no exact complete
            # player market, the projection remains unpublished.
            ignored_rapid_ace_df = {"aces": 0, "double_faults": 0}
            for event_id, markets in list(available_projection_markets.items()):
                trusted = set(markets)
                for metric in ("aces", "double_faults"):
                    if metric in trusted:
                        ignored_rapid_ace_df[metric] += 1
                        trusted.discard(metric)
                available_projection_markets[event_id] = trusted
            projection_discovery_report["ace_df_real_odds_policy"] = "propline_only_v1"
            projection_discovery_report["rapidapi_ace_df_markets_ignored"] = ignored_rapid_ace_df

            # Primary Match Winner enrichment runs first. PropLine is a true
            # fallback: it may fill only contracts that provider 1 did not price.
            # The same PropLine event/odds calls also cover Aces/DF/Sets/Games,
            # so adding h2h fallback does not create a second board sweep.
            predictions, odds_report = enrich_current_betting_day_odds(
                provider, predictions, now=selection_now,
                max_events=projection_odds_cap, provider_id=1,
                timezone_name="Europe/Bratislava",
                start_hour=args.betting_day_start_hour,
                prefetched_payloads=projection_market_cache,
            )

            # Paid/API requests only run as part of an explicitly authorized
            # refresh (the existing workflow auto-refresh gate is unchanged).
            # PropLine has its own independent 1000/day quota and keeps a hard
            # reserve. Its h2h output is used only when the primary provider left
            # the Match Winner contract unpriced; primary quotes are never replaced.
            prop_key = os.getenv("PROPL", "").strip()
            if prop_key and args.propline_max_events:
                propline_existing = {
                    event_id: set(markets)
                    for event_id, markets in available_projection_markets.items()
                }
                primary_match_winner = 0
                for row in predictions:
                    event_id = str(row.get("event_id") or "").strip()
                    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
                    if event_id and betting.get("market") == "match_winner" and betting.get("odds"):
                        propline_existing.setdefault(event_id, set()).add("match_winner")
                        primary_match_winner += 1

                prop_client = PropLineClient(
                    prop_key, max_calls=1 + 2 * args.propline_max_events,
                    min_remaining=150,
                )
                prop_market_payloads, prop_report = discover_propline_fallback(
                    prop_client, predictions, propline_existing,
                    now=now, max_events=args.propline_max_events,
                )

                match_winner_fallback_attached = 0
                for index, row in enumerate(predictions):
                    event_id = str(row.get("event_id") or "").strip()
                    if not event_id:
                        continue
                    betting = row.get("betting") if isinstance(row.get("betting"), dict) else {}
                    if betting.get("market") == "match_winner" and betting.get("odds"):
                        continue
                    quote = (prop_market_payloads.get(event_id) or {}).get("match_winner")
                    if not isinstance(quote, dict):
                        continue
                    p1 = row.get("player1") if isinstance(row.get("player1"), dict) else {}
                    p2 = row.get("player2") if isinstance(row.get("player2"), dict) else {}
                    market = extract_match_winner_odds(
                        quote.get("payload"),
                        str(p1.get("name") or ""),
                        str(p2.get("name") or ""),
                    )
                    if market is None:
                        continue
                    try:
                        captured_at = datetime.fromisoformat(
                            str(quote.get("captured_at") or "").replace("Z", "+00:00")
                        )
                        if captured_at.tzinfo is None:
                            captured_at = captured_at.replace(tzinfo=timezone.utc)
                    except (TypeError, ValueError):
                        captured_at = selection_now
                    enriched = attach_match_winner_market(
                        row, market, captured_at=captured_at,
                        provider_id=2, betting_day=odds_report.get("betting_day"),
                    )
                    provenance = {
                        "source": "propline",
                        "bookmaker": quote.get("bookmaker"),
                        "provider_event_id": quote.get("provider_event_id"),
                    }
                    if isinstance(enriched.get("match_winner_market"), dict):
                        enriched["match_winner_market"].update(provenance)
                    if isinstance(enriched.get("betting"), dict):
                        enriched["betting"].update({
                            "odds_source": "propline",
                            "odds_bookmaker": quote.get("bookmaker"),
                            "odds_provider_event_id": quote.get("provider_event_id"),
                        })
                    predictions[index] = enriched
                    match_winner_fallback_attached += 1

                for rapid_id, by_metric in prop_market_payloads.items():
                    for metric, quote in by_metric.items():
                        if metric == "match_winner":
                            continue
                        available_projection_markets.setdefault(rapid_id, set()).add(metric)
                        if metric in ("games", "sets"):
                            bookmaker_lines_by_event.setdefault(rapid_id, {})[metric] = [
                                float(line["line"]) for line in
                                extract_match_total_odds(quote["payload"], metric)
                            ]

                prop_report["match_winner_primary_preserved"] = primary_match_winner
                prop_report["match_winner_fallback_attached"] = match_winner_fallback_attached
                prop_report["fallback_order"] = [
                    "primary_match_winner", "propline_match_winner",
                    "propline_aces_df_sets_games",
                ]
                prop_report["clv_followup"] = "published_offer_priority"
                projection_discovery_report["propline"] = prop_report
                print(json.dumps({"propline_market_audit": prop_report}, ensure_ascii=False), flush=True)
            else:
                projection_discovery_report["propline"] = {
                    "enabled": False, "reason": (
                        "PROPL_secret_missing" if not prop_key else "disabled_by_event_cap"
                    ), "calls": 0,
                }
        # In odds-first mode the projection models operate only on events
        # that have a complete matching market from the provider. Keep an
        # expanded *eligible* pool so publication can independently rank each
        # of the four categories without one consuming the others' slots.
        projection_pool_per_market = (
            max(30, min(200, projection_odds_cap)) if projection_odds_cap else 10
        )
        ace_picks, ace_report = select_ace_picks(
            matches, predictions, now=selection_now,
            per_market_limit=projection_pool_per_market,
            total_limit=2 * projection_pool_per_market,
            target_count=projection_pool_per_market,
            available_markets_by_event=(
                available_projection_markets if projection_odds_cap else None
            ),
        )
        sg_picks, sg_report = select_sg_picks(
            matches, predictions, now=selection_now,
            per_market_limit=projection_pool_per_market,
            total_limit=2 * projection_pool_per_market,
            target_count=projection_pool_per_market,
            available_markets_by_event=(
                available_projection_markets if projection_odds_cap else None
            ),
            bookmaker_lines_by_event=(
                bookmaker_lines_by_event if projection_odds_cap else None
            ),
        )
        projection_odds_report["discovery"] = projection_discovery_report
        if projection_odds_cap and (ace_picks or sg_picks):
            ace_picks, sg_picks, attachment_report = enrich_projection_odds(
                provider, ace_picks, sg_picks,
                max_events=projection_odds_cap, provider_id=1,
                prefetched_payloads=projection_market_cache,
                alternate_market_payloads=prop_market_payloads,
            )
            projection_odds_report.update(attachment_report)
            projection_odds_report["discovery"] = projection_discovery_report
        # Market-first publication is strict: an unmatched card remains an
        # internal model diagnostic, never a bookmaker-looking bet.
        if projection_odds_cap:
            projection_odds_report["unpriced_model_candidates"] = {
                market: sum(row.get("market") == market and
                            row.get("price_status") != "priced_projection"
                            for row in ace_picks + sg_picks)
                for market in ("aces", "double_faults", "games", "sets")
            }
            # Do not publish penny-price bets or a confidence-derived estimate:
            # the bookmaker quote must belong to this exact market contract.
            def publishable_api_price(row):
                try:
                    odds = float(row.get("odds") or 0)
                    provider = int(row.get("provider_id") or 0)
                except (TypeError, ValueError, OverflowError):
                    return False
                market = str(row.get("market") or "").strip().lower()
                source = str(row.get("odds_source") or "").strip().lower()
                ace_df_real_api = (
                    market not in ("aces", "double_faults")
                    or (
                        row.get("odds_contract_version") == "ace_df_real_api_v1"
                        and (
                            (source == "rapidapi" and provider == 1)
                            or (
                                source == "propline"
                                and provider == 2
                                and bool(row.get("odds_bookmaker"))
                            )
                        )
                    )
                )
                return (
                    row.get("price_status") == "priced_projection"
                    and provider > 0 and bool(row.get("captured_at"))
                    and 1.50 <= odds < float("inf")
                    and ace_df_real_api
                )
            ace_picks = [row for row in ace_picks if publishable_api_price(row)]
            sg_picks = [row for row in sg_picks if publishable_api_price(row)]
        # Ten per independent category, sorted by validated projection
        # confidence and evidence, NOT simply by the highest bookmaker price.
        def priced_first_ten(rows):
            indexed = list(enumerate(rows))
            chosen = []
            for metric in ("aces", "double_faults", "sets", "games"):
                group = [(i, row) for i, row in indexed if row.get("market") == metric]
                group.sort(key=lambda pair: (
                    str(pair[1].get("price_status") or "") == "priced_projection",
                    -pair[0],
                ), reverse=True)
                chosen.extend(group[:10])
            chosen.sort(key=lambda pair: pair[0])
            return [row for _, row in chosen]

        ace_picks = priced_first_ten(ace_picks)
        sg_picks = priced_first_ten(sg_picks)
        projection_odds_report["published_priced_cards"] = {
            metric: sum(
                row.get("market") == metric
                and row.get("price_status") == "priced_projection"
                for row in ace_picks + sg_picks
            )
            for metric in ("aces", "double_faults", "sets", "games")
        }
        if isinstance(ace_report, dict):
            ace_report = {
                **ace_report, "odds_attachment": projection_odds_report,
                "published_selected": len(ace_picks),
                "priced_selection_policy": "odds_first_exact_market_then_model_independent_top10",
            }
        if isinstance(sg_report, dict):
            sg_report = {
                **sg_report, "odds_attachment": projection_odds_report,
                "published_selected": len(sg_picks),
                "priced_selection_policy": "odds_first_exact_market_then_model_independent_top10",
            }
    except Exception as exc:
        refresh_error = exc
    finally:
        try:
            provider.client.close()
        finally:
            budget.close()

    if refresh_error is not None:
        # Partial completed history is checkpointed, but no new prediction
        # feed is published from an incomplete refresh.
        raise refresh_error
    if args.morning_refresh:
        # A single job waits without spending provider requests, then publishes.
        delay = morning_publication_delay(
            datetime.now(timezone.utc), start_hour=args.betting_day_start_hour
        )
        if delay:
            print(json.dumps({"morning_publish_wait_seconds": round(delay, 1)}), flush=True)
            time.sleep(delay)
    settlement_history = matches
    if current_only:
        settlement_cutoff = now - timedelta(days=14)
        settlement_history = [
            match for match in matches
            if match.scheduled_at >= settlement_cutoff
        ]
        print(json.dumps({
            "current_refresh_settlement": {
                "history_matches_total": len(matches),
                "history_matches_checked": len(settlement_history),
                "cutoff": settlement_cutoff.isoformat(),
            }
        }), flush=True)

    feed = _publish_predictions(
        prediction_store, prediction_ledger,
        predictions, matches, model, report, upcoming,
        odds_report=odds_report, ace_picks=ace_picks, ace_report=ace_report,
        sg_picks=sg_picks, sg_report=sg_report,
        doubles_picks=doubles_picks, doubles_report=doubles_report,
        doubles_matches=doubles_completed, doubles_upcoming=doubles_upcoming,
        prior_feed=prior_feed, prior_snapshot=prior_snapshot,
        settlement_matches=settlement_history,
        betting_day_start_hour=args.betting_day_start_hour,
        morning_refresh=args.morning_refresh,
    )
    target = ROOT / "api/data/feed.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    write_json(target, feed)
    refresh_report = {
        "requests": provider.request_count,
        "upcoming": len(feed["upcoming"]),
        "top200": len(feed.get("top200_picks", [])),
        "daily": len(feed.get("top_daily_picks", [])),
        "prime": len(feed.get("prime_picks", [])),
        "value": len(feed.get("value_picks", [])),
        "ace": len(feed.get("ace_picks", [])),
        "ace_projection": ace_report or {},
        "ace_df_settlement_statistics": ace_df_settlement_stats_report or {},
        "sg": len(feed.get("sg_picks", [])),
        "sg_projection": sg_report or {},
        "doubles": len(feed.get("doubles_picks", [])),
        "doubles_model": doubles_report or {},
        "odds": odds_report or {},
        "settled": len(feed["results"]),
        "model": model.version,
        "shadow": {
            "enabled": shadow_enabled,
            "challenger_model": challenger_version or None,
            "captured": (shadow_report.get("cohort") or {}).get("captured", 0),
            "settled": (shadow_report.get("cohort") or {}).get("settled", 0),
            "minimum_for_review": (shadow_report.get("cohort") or {}).get("minimum_for_review", 200),
            "ready_for_promotion_review": (shadow_report.get("gate") or {}).get("ready_for_promotion_review", False),
        },
    }
    write_json(prediction_dir / "refresh_report.json", refresh_report)
    print(json.dumps(refresh_report))


if __name__ == "__main__":
    main()
