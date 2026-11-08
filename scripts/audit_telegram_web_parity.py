"""Deterministic read-only Telegram vs website Results and sent-receipt audit.

The frozen Telegram send receipt defines which bets existed. Provider-verified
Results archive defines their terminal outcomes. The website's exact pre-tier
backend Results projection is an *independent serving view*. Never use a
winner, a changed line, or an alternate publication as settlement evidence.
No provider calls, CDB writes, Telegram sends, or data repair.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import date, datetime, timezone, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import urllib.request

import telegram_daily_results as results
import telegram_offer_publisher as tg

MAX_RESPONSE = 5_000_000
DEFAULT_URL = "https://agreeable-sky-011a7fe10.7.azurestaticapps.net"


def _fetch_site(url: str, day: str) -> dict:
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+", url):
        raise ValueError("Site URL must be HTTPS")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
        raise ValueError("Invalid day")
    key = os.getenv("BLINQ_LIVE_WORKER_TOKEN") or ""
    if not key:
        raise RuntimeError("Existing read-only worker credential missing")
    req = urllib.request.Request(
        url + "/api/v1/internal/telegram/site-results-parity?day=" + day,
        headers={"Accept": "application/json", "X-Blinq-Worker-Token": key},
    )
    with urllib.request.urlopen(req, timeout=30) as conn:
        if conn.status != 200:
            raise RuntimeError("Website parity source unavailable")
        body = conn.read(MAX_RESPONSE + 1)
    if len(body) > MAX_RESPONSE:
        raise RuntimeError("Website parity response exceeds limit")
    obj = json.loads(body)
    if (not isinstance(obj, dict) or obj.get("schema") != 1
            or obj.get("betting_day") != day
            or obj.get("source") != "website_results_pre_entitlement_v1"
            or obj.get("member_render_verified") is not False
            or obj.get("provider_requests") != 0
            or not isinstance(obj.get("rows"), list)
            or obj.get("results_archive_unavailable") is not False
            or obj.get("results_exclusions_unavailable") is not False):
        raise RuntimeError("Website parity source is not independently complete")
    return obj


def _fingerprint(ref: dict) -> str:
    frozen = "|".join(str(ref.get(k) or "") for k in (
        "event_id", "section", "market", "selection_id",
        "publication_key", "market_line", "projection_direction",
    ))
    return sha256(frozen.encode()).hexdigest()[:16]


def _has_exact_issued_identity(ref: dict, row: dict) -> bool:
    """Audit-only structural check; never grade or reprice this candidate."""
    if not isinstance(row, dict):
        return False
    if any(str(row.get(key) or "") != str(ref.get(key) or "")
           for key in ("event_id", "selection_id", "section", "market")):
        return False
    frozen_pub = str(ref.get("publication_key") or "")
    if frozen_pub and frozen_pub != str(row.get("publication_key") or ""):
        return False
    if ref.get("market") == "aces":
        if str(ref.get("market_line") or "") != str(row.get("market_line") or ""):
            return False
        if str(ref.get("projection_direction") or "") != str(row.get("projection_direction") or ""):
            return False
    return True


def _evidence(ref: dict, rows: list[dict]) -> tuple[str, dict | None, str]:
    try:
        original = results.match_result(ref, rows)
    except RuntimeError:
        return "ambiguous", None, "ambiguous_exact_contract"
    if original is None:
        # The canonical Results matcher intentionally rejects unverified
        # provenance. Audit structure separately, but never treat it as a
        # verified settlement or allow it to influence ROI/results.
        structural = [row for row in rows if _has_exact_issued_identity(ref, row)]
        if len(structural) > 1:
            return "ambiguous", None, "ambiguous_exact_contract"
        return "pending", None, (
            "no_verified_final" if structural else "no_exact_contract"
        )
    result = original.get("result")
    if not isinstance(result, dict) or result.get("runtime_source") != "match_status_snapshot":
        return "pending", original, "no_verified_final"
    if result.get("void") is True:
        return "void", original, "exact"
    if type(result.get("correct")) is bool:
        return ("won" if result["correct"] else "lost"), original, "exact"
    return "pending", original, "no_verified_final"


def reconcile_day(day: str, sent: list[dict], archived: list[dict],
                  site: dict, receipt: dict | None, *,
                  now: datetime | None = None) -> dict:
    if site.get("source") != "website_results_pre_entitlement_v1" or site.get("betting_day") != day:
        raise ValueError("Website parity source/day mismatch")
    if not isinstance(site.get("rows"), list):
        raise ValueError("Missing site row projection")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Clock must be timezone-aware")
    counts = Counter()
    reasons = Counter()
    site_gaps = Counter()  # Only broad market and verification class, never identifiers.
    site_absence = Counter()  # Cohort-level structural diagnostics, no raw IDs.
    fingerprints: dict[str, list[str]] = {}
    premium = Counter()
    site_rows = site["rows"]
    # Worker-only aggregation: expose where already verified archive rows went
    # during the read-side Results merge without logging identities or quotes.
    raw_merge = site.get("archive_merge_diagnostics")
    merge_diagnostics = {}
    if isinstance(raw_merge, dict):
        for name in ("archive_contract_not_merged", "archive_contract_shifted_betting_day"):
            count = raw_merge.get(name)
            if type(count) is int and 0 <= count <= 25000:
                merge_diagnostics[name] = count
    for ref in sent:
        channel = ref.get("channel")
        a, ar, diagnostic = _evidence(ref, archived)
        b, br, site_reason = _evidence(ref, site_rows)
        counts["issued"] += 1
        if channel == "free":
            counts["free_mirror_refs"] += 1
        else:
            premium[a] += 1
        counts["archive_" + a] += 1
        counts["site_" + b] += 1
        issues = []
        if a == "ambiguous":
            issues.append("archive_ambiguous")
        elif a == "pending" and (receipt or now.date() >= date.fromisoformat(day) + timedelta(days=2)):
            issues.append("overdue_exact_archive_missing")
        if b == "ambiguous":
            issues.append("site_ambiguous")
        elif a in ("won", "lost", "void") and b == "pending":
            issues.append("site_missing_exact_archive_result")
            market = str(ref.get("market") or "").lower()
            market = market if market in {"aces", "match_winner", "double_faults"} else "other"
            kind = site_reason if site_reason in {"no_exact_contract", "no_verified_final"} else "other"
            site_gaps[market + ":" + kind] += 1
            if kind == "no_exact_contract":
                same_event = [row for row in site_rows if (
                    str(row.get("event_id") or "") == str(ref.get("event_id") or "")
                )]
                if not same_event:
                    site_absence[market + ":event_absent"] += 1
                elif any(
                    str(row.get("section") or "") == str(ref.get("section") or "")
                    and str(row.get("market") or "") == str(ref.get("market") or "")
                    and str(row.get("selection_id") or "") == str(ref.get("selection_id") or "")
                    for row in same_event
                ):
                    site_absence[market + ":selection_present_other_contract"] += 1
                else:
                    site_absence[market + ":event_present_other_selection"] += 1
        elif a in ("won", "lost", "void") and b not in (a, "pending"):
            issues.append("site_terminal_outcome_conflict")
        if ar is not None and br is not None:
            def quote(row):
                return tg.num(row.get("odds"))
            # The website Results contract must retain the issued quote;
            # alternate inferred price or next-day board odds are not proof.
            offered = quote(ref)
            for source_name, row in (("archive", ar), ("website", br)):
                current = quote(row)
                if (offered is None) != (current is None) or (
                    offered is not None and current is not None
                    and abs(offered - current) > 0.000001
                ):
                    issues.append(source_name + "_price_changed")
            if (ar.get("result") or {}).get("actual_count") != (br.get("result") or {}).get("actual_count"):
                issues.append("site_player_statistic_conflict")
        for issue in sorted(set(issues)):
            reasons[issue] += 1
            fingerprints.setdefault(issue, []).append(_fingerprint(ref))
    received = receipt if isinstance(receipt, dict) and receipt.get("status") == "sent" else None
    if receipt and not received:
        reasons["result_receipt_not_confirmed"] += 1
    if received:
        previous = received.get("counts")
        if not isinstance(previous, dict) or any(
            previous.get(k) != premium[k]
            for k in ("won", "lost", "void", "pending")
        ):
            reasons["delivered_summary_vs_verified_archive_mismatch"] += 1
    # A posted Results report must never be counted twice via FREE.
    expected_total = sum(premium.values())
    if expected_total + counts["free_mirror_refs"] != len(sent):
        raise AssertionError("Invalid independent channel totals")
    return {
        "day": day,
        "issued_references": len(sent),
        "premium_references": expected_total,
        "free_mirror_references": counts["free_mirror_refs"],
        "archive": {k: counts["archive_" + k] for k in ("won", "lost", "void", "pending", "ambiguous")},
        "website_pre_entitlement": {k: counts["site_" + k] for k in ("won", "lost", "void", "pending", "ambiguous")},
        "recorded_telegram_results_sent": received is not None,
        "recorded_telegram_results_counts": received.get("counts") if received else None,
        "recomputed_premium_counts": {k: premium[k] for k in ("won", "lost", "void", "pending", "ambiguous")},
        "website_all_published_sections": site.get("published_sections"),
        "website_excluded_sections": site.get("excluded_sections"),
        "parity": "mismatch" if reasons else "verified_same_contract",
        "mismatch_reasons": dict(sorted(reasons.items())),
        "site_gap_breakdown": dict(sorted(site_gaps.items())),
        "site_absence_breakdown": dict(sorted(site_absence.items())),
        "archive_merge_diagnostics": merge_diagnostics,
        "private_fingerprints": {k: sorted(v)[:20] for k, v in sorted(fingerprints.items())},
        "scope": "telegram_issued_vs_website_pre_entitlement",
        "member_account_render_verified": False,
        "provider_requests": 0, "cdb_writes": 0,
        "telegram_sends": 0, "archive_writes": 0,
    }


def audit(state: dict, base: str, days: list[str], *, now=None, site_reader=_fetch_site, archive_reader=None) -> dict:
    if not isinstance(state, dict) or not isinstance(state.get("attempts"), dict):
        raise ValueError("Missing private Telegram attempts")
    if len(days) < 1 or len(days) > 14 or len(set(days)) != len(days):
        raise ValueError("Audit must scope one to fourteen distinct days")
    archive_reader = archive_reader or results.archive
    details = []
    for day in sorted(days):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", day):
            raise ValueError("Invalid day")
        sent = results.extract_sent(state, day)
        if not sent:
            details.append({"day": day, "status": "no_sent_offer"})
            continue
        archive_rows = archive_reader(base, day)
        site = site_reader(base, day)
        receipt = state["attempts"].get("results:" + day)
        details.append(reconcile_day(day, sent, archive_rows, site, receipt, now=now))
    problems = [x for x in details if x.get("parity") == "mismatch"]
    return {
        "schema": 1, "status": "mismatch" if problems else "pass",
        "checked_days": len(details), "days_with_disagreement": len(problems),
        "reports": details, "complete_member_render_verification": False,
        "paid_provider_requests": 0, "cdb_writes": 0,
        "telegram_sends": 0, "archive_writes": 0,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", required=True)
    ap.add_argument("--url", default=DEFAULT_URL)
    ap.add_argument("--days", nargs="+", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--mode", choices=("observe", "enforce"), default="enforce")
    args = ap.parse_args()
    report = audit(tg.load(args.state), args.url, args.days)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    # Aggregate log only; exact failed identity fingerprints remain in
    # the short-retention private workflow artifact.
    for item in report["reports"]:
        print("TELEGRAM_WEBSITE_PARITY " + json.dumps({
            k: v for k, v in item.items() if k not in (
                "private_fingerprints", "recorded_telegram_results_counts",
            )
        }, sort_keys=True), flush=True)
    print("TELEGRAM_WEBSITE_PARITY_SUMMARY " + json.dumps({
        k: v for k, v in report.items() if k != "reports"
    }, sort_keys=True), flush=True)
    return 2 if args.mode == "enforce" and report["status"] != "pass" else 0


if __name__ == "__main__":
    raise SystemExit(main())
