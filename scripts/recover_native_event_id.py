"""Fail-closed native TennisApi event-ID recovery from independently fetched day calendars.

Only already-canonical, completed singles with source-category provenance are
eligible. A name, score, guessed event number or foreign-provider ID is NEVER
sufficient. Pure in-memory metadata change; the existing canonical writer owns
locking, persistence, backup, CAS and remote read-back.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import date, datetime, timezone
import re

from tbt.services.statistics_gapfill import event_id, missing_fields

ROUND_ALIASES = {
    "final": "f", "f": "f", "semifinal": "sf", "semi final": "sf",
    "sf": "sf", "quarterfinal": "qf", "quarter final": "qf", "qf": "qf",
    "round of 16": "r16", "round of 32": "r32",
    "round of 64": "r64", "round of 128": "r128",
}


def _round(value):
    token = " ".join(re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).split())
    return ROUND_ALIASES.get(token, token)


def _category(match):
    raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    cid = raw.get("_tbt_source_category_id")
    return str(cid) if cid is not None and str(cid).isascii() and str(cid).isdigit() and int(cid) > 0 else ""


def _day(match):
    dt = match.scheduled_at
    if not isinstance(dt, datetime) or dt.tzinfo is None:
        return None
    return dt.astimezone(timezone.utc).date()


def _pair(match):
    ids = (str(match.player1_id or ""), str(match.player2_id or ""))
    return tuple(sorted(ids)) if all(ids) and ids[0] != ids[1] else ()


def _id_claims(match):
    raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
    native = [raw.get(k) for k in (
        "_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id")]
    marker = raw.get("_tbt_event_identity")
    if isinstance(marker, dict):
        native.append(marker.get("event_id"))
    return {str(v) for v in native if v not in (None, "")}


def eligible(match):
    """Only recovery of absent IDs from already first-party canonical records."""
    return (str(match.tour or "").lower() in {"atp", "wta"}
            and bool(getattr(match, "is_completed", False))
            and bool(_category(match)) and bool(_pair(match))
            and str(match.winner_id or "") in _pair(match)
            and bool(_round(match.round_name)) and bool(_day(match))
            and not _id_claims(match) and event_id(match) is None
            and bool(missing_fields(match)))


def candidate_days(canonical, *, start: date, end: date, attempts=None,
                   today: date | None = None, max_days=40):
    """Batch candidates by calendar date, preferring 2024-26 and larger gaps.

    Cool down successfully scanned days (7d if partial gain, otherwise 30d).
    Retains historical coverage without repeatedly billing known-empty dates.
    """
    if not 1 <= max_days <= 366:
        raise ValueError("Invalid maximum number of calendar days")
    today = today or datetime.now(timezone.utc).date()
    attempts = attempts or {}
    counts = Counter()
    for m in canonical:
        if eligible(m) and start <= _day(m) <= end:
            counts[(_day(m).isoformat(), m.tour.lower())] += 1
    groups = defaultdict(set)
    for (day, tour), _ in counts.items():
        prior = attempts.get(day) or {}
        if prior.get("at"):
            try:
                last = date.fromisoformat(str(prior["at"])[:10])
                cooldown = 7 if int(prior.get("recovered", 0)) > 0 else 30
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid persisted identity cooldown") from exc
            if (today - last).days < cooldown:
                continue
        groups[day].add(tour)
    keys = sorted(groups, key=lambda d: (
        0 if 2024 <= int(d[:4]) <= 2026 else 1,
        -sum(counts[(d, t)] for t in groups[d]),
        -int(d.replace("-", ""))))
    return [(date.fromisoformat(d), tuple(sorted(groups[d])),
             sum(counts[(d, t)] for t in groups[d])) for d in keys[:max_days]]



def identity_gap_inventory(canonical, *, start: date, end: date,
                           attempts=None, today: date | None = None,
                           max_days=40):
    """Explain why missing TennisApi IDs cannot enter the guarded API queue.

    Counts are aggregate-only, with no player/event IDs or raw matches. This
    distinguishes an unresolved canonical source-scope from provider calendar
    cooldowns. It does not generate new identity evidence or authorize writes.
    """
    today = today or datetime.now(timezone.utc).date()
    attempts = attempts or {}
    reasons = Counter()
    by_cohort = defaultdict(Counter)
    eligible_days = defaultdict(int)
    eligible_tours_by_day = defaultdict(set)
    counted = 0
    claim_details = Counter()
    secondary_blockers = Counter()
    for match in canonical:
        day = _day(match)
        if (str(match.tour or "").lower() not in {"atp", "wta"}
                or day is None or not start <= day <= end
                or not getattr(match, "is_completed", False)
                or not missing_fields(match) or event_id(match) is not None):
            continue
        counted += 1
        claims = _id_claims(match)
        pair = _pair(match)
        if claims:
            reason = "existing_unusable_or_conflicting_event_claims"
            raw = match.provider_payload if isinstance(match.provider_payload, dict) else {}
            keys = ("_tbt_provider_event_id", "provider_event_id", "event_id", "eventId", "id")
            native_claim = raw.get("_tbt_provider_event_id")
            if native_claim not in (None, ""):
                claim_details["explicit_native_provider_claim"] += 1
            elif raw.get("_tbt_event_identity"):
                claim_details["identity_witness_without_explicit_native_claim"] += 1
            elif any(raw.get(k) not in (None, "") for k in keys[1:]):
                claim_details["unscoped_event_claim"] += 1
            else:
                claim_details["other_claim"] += 1
            if len(claims) > 1:
                claim_details["multiple_distinct_claim_values"] += 1
            if not all(c.isascii() and c.isdigit() and int(c) > 0 for c in claims):
                claim_details["non_positive_or_nonnumeric_claim"] += 1
            # Independent, overlapping blockers: claims must not hide metadata gaps.
            if not _category(match):
                secondary_blockers["missing_first_party_category"] += 1
            if not pair:
                secondary_blockers["missing_or_colliding_player_ids"] += 1
            if str(match.winner_id or "") not in pair:
                secondary_blockers["winner_outside_pair"] += 1
            if not _round(match.round_name):
                secondary_blockers["missing_round"] += 1
        elif not _category(match):
            reason = "missing_first_party_category"
        elif not pair:
            reason = "missing_or_colliding_player_ids"
        elif str(match.winner_id or "") not in pair:
            reason = "winner_outside_pair"
        elif not _round(match.round_name):
            reason = "missing_round"
        else:
            reason = "eligible_native_calendar"
            eligible_days[day.isoformat()] += 1
            eligible_tours_by_day[day.isoformat()].add(str(match.tour).lower())
        reasons[reason] += 1
        by_cohort[f"{str(match.tour).lower()}:{day.year}"][reason] += 1

    pending = candidate_days(canonical, start=start, end=end,
                             attempts=attempts, today=today, max_days=max_days)
    pending_dates = {day.isoformat() for day, _, _ in pending}
    cooldown_rows = 0
    cooldown_days = 0
    unselected_rows = 0
    for day, count in eligible_days.items():
        if day in pending_dates:
            continue
        prior = attempts.get(day)
        if isinstance(prior, dict) and prior.get("at"):
            try:
                last = date.fromisoformat(str(prior["at"])[:10])
                cooldown = 7 if int(prior.get("recovered", 0)) > 0 else 30
                blocked = (today - last).days < cooldown
            except (ValueError, TypeError) as exc:
                raise ValueError("Invalid persisted identity cooldown") from exc
            if blocked:
                cooldown_rows += count
                cooldown_days += 1
                continue
        unselected_rows += count
    if sum(reasons.values()) != counted:
        raise AssertionError("Identity gap accounting differs from candidate rows")
    return {
        "schema": 1,
        "status": "IDENTITY_GAP_READ_ONLY_INVENTORY",
        "canonical_missing_or_conflicting_id_rows": counted,
        "primary_blockers": dict(sorted(reasons.items())),
        "existing_claim_diagnostics": dict(sorted(claim_details.items())),
        "existing_claim_secondary_blockers": dict(sorted(secondary_blockers.items())),
        "by_tour_year": {
            name: dict(sorted(value.items()))
            for name, value in sorted(by_cohort.items())
        },
        "eligible_unique_calendar_days": len(eligible_days),
        "eligible_native_calendar_rows": reasons["eligible_native_calendar"],
        "cooldown_blocked_days": cooldown_days,
        "cooldown_blocked_rows": cooldown_rows,
        "eligible_rows_outside_top_day_limit": unselected_rows,
        "scheduled_days": len(pending),
        "scheduled_eligible_rows": sum(item[2] for item in pending),
        "native_provider_requests": 0,
        "cdb_writes": 0,
        "identity_attested_by_audit": False,
    }


def recover_day(canonical, provider_events, *, day: date):
    """Promote only unique same-provider events to native metadata, in memory.

    Reject every provider/canonical one-to-many collision. Recovered rows carry
    the native event and participant IDs, not imported stats or guessed fields.
    """
    report = Counter()
    sources = defaultdict(list)
    claimed = defaultdict(set)
    for match in canonical:
        for ident in _id_claims(match):
            if ident.isascii() and ident.isdigit():
                claimed[(str(match.tour).lower(), ident)].add(str(match.match_id))
    for event in provider_events:
        raw = event.provider_payload if isinstance(event.provider_payload, dict) else {}
        witness = raw.get("_tbt_event_identity")
        if (not isinstance(witness, dict) or witness.get("status") != "finished"
                or not _category(event) or not _pair(event)
                or set(map(str, (witness.get("home"), witness.get("away")))) != set(_pair(event))
                or not getattr(event, "is_completed", False)
                or str(event.winner_id or "") not in _pair(event)
                or not _round(event.round_name) or not _day(event)
                or abs((_day(event) - day).days) > 1):
            report["rejected_unverified_provider_event"] += 1
            continue
        ident = event_id(event)
        if not ident or str(witness.get("event_id")) != ident:
            report["rejected_conflicting_provider_id"] += 1
            continue
        key = (event.tour.lower(), _category(event), _pair(event), _round(event.round_name))
        sources[key].append(event)

    proposals = defaultdict(list)
    for match in canonical:
        if not eligible(match) or _day(match) != day:
            continue
        report["eligible_on_day"] += 1
        key = (match.tour.lower(), _category(match), _pair(match), _round(match.round_name))
        found = [row for row in sources.get(key, ()) if
                 str(row.winner_id) == str(match.winner_id)
                 and abs((_day(row) - _day(match)).days) <= 1
                 and not (str(row.surface or "").strip() and str(match.surface or "").strip()
                          and str(row.surface).lower().strip() != str(match.surface).lower().strip())]
        if len(found) != 1:
            report["unresolved_no_unique_native_event"] += 1
            continue
        row = found[0]
        ident = event_id(row)
        if claimed[(match.tour.lower(), ident)] - {str(match.match_id)}:
            report["quarantine_provider_id_claimed_elsewhere"] += 1
            continue
        proposals[(match.tour.lower(), ident)].append((match, row))

    changes = {}
    for (tour, ident), items in proposals.items():
        if len(items) != 1:
            report["quarantine_many_canonical_to_one_native"] += len(items)
            continue
        match, row = items[0]
        previous = dict(match.provider_payload or {})
        if _id_claims(match):
            report["quarantine_existing_identity_claim"] += 1
            continue
        witness = dict(row.provider_payload["_tbt_event_identity"])
        match.provider_payload = {
            **previous, "_tbt_provider_event_id": ident,
            "_tbt_event_identity": witness,
        }
        if event_id(match) != ident or match.provider_payload["_tbt_event_identity"] != witness:
            match.provider_payload = previous
            raise RuntimeError("Recovered identity failed local readback")
        changes[str(match.match_id)] = {
            "tour": tour, "year": _day(match).year,
            "event_id": ident, "category_id": _category(match),
            "home": str(witness["home"]),
            "away": str(witness["away"]),
        }
        claimed[(tour, ident)].add(str(match.match_id))
        report["recovered"] += 1
    report["same_provider_only"] = True
    report["raw_stats_mutated"] = False
    return changes, dict(report)
