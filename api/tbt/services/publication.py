"""Lightweight prediction publication state transitions.

This module intentionally depends only on the Python standard library so the
post-deploy confirmation step does not require the training/scientific stack.
"""
from __future__ import annotations

from datetime import datetime, timezone


def confirm_publication(ledger, published_event_ids, now=None):
    """Confirm first public availability after a successful deployment.

    Only event IDs present in the deployed feed are eligible for confirmation.
    Confirmation is conservative: if the match has already started, the record
    is excluded rather than backdated. Existing issued_at values are immutable.
    """
    now = now or datetime.now(timezone.utc)
    published = {str(value) for value in published_event_ids}
    confirmed = []
    for source in ledger:
        row = dict(source)
        if row.get("issued_at") or row.get("event_id") not in published:
            confirmed.append(row)
            continue
        scheduled_at = datetime.fromisoformat(row["scheduled_at"])
        if scheduled_at <= now:
            row["publication_status"] = "expired_unpublished"
            row["excluded_reason"] = "not_confirmed_before_start"
        else:
            row["issued_at"] = now.isoformat()
            row["publication_status"] = "published"
        confirmed.append(row)
    return sorted(confirmed, key=lambda r: r["scheduled_at"])
