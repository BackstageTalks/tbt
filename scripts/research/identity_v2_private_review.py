"""Explicit opt-in LOCAL-ONLY reviewer pack; NEVER run in GitHub CI.

The historical PR runner prints aggregate counts, not source rows. This helper
can preserve bounded disputed cases for offline independent official ID review,
but ONLY on a private workstation with an already existing mode-0700 directory.

No network, CDB writer, provider API, model usage or source file mutation.
No names/IDs are returned to the public CI summary. Do not commit packs.
"""
from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import os
from pathlib import Path
import stat

from scripts.research.identity_v2 import Event, EventCandidate
from scripts.research.identity_v2_triage import ReviewCase

MAX_LIMIT = 5000
REVIEW_BUCKETS = {
    "old_unique_became_ambiguous", "old_unique_replaced",
    "old_candidate_lost", "old_ambiguous_changed",
    "candidate_sets_disagree", "new_only_ambiguous",
    "new_only_unique_strong_context", "new_only_unique_weak_context",
    "old_ambiguous_now_unique"
}


def _event_payload(event: Event) -> dict:
    return {
        "namespace": event.namespace,
        "event_id": event.event_id,
        "tour": event.tour,
        "date_semantics": event.date_kind,
        "event_date": event.event_date,
        "tournament": event.tournament,
        "source_edition_id": event.edition_id,
        "draw": event.draw,
        "round": event.round_name,
        "score": event.score,
        "players": [
            {"namespace": p.namespace, "native_id": p.native_id,
             "name": p.name} for p in event.players
        ],
        "winner_native_id": event.winner_native_id,
    }


class PrivateReviewPack:
    def __init__(self, max_items: int = 1250):
        if not 1 <= max_items <= MAX_LIMIT:
            raise ValueError("Review pack size must be 1..5000")
        self.max_items = max_items
        self._rows: list[tuple[tuple, dict]] = []

    def consider(self, family: str, source: Event, old: list[Event],
                 new: list[EventCandidate], review: ReviewCase) -> None:
        if review.bucket not in REVIEW_BUCKETS:
            return
        if review.independently_verified or review.cdb_write_authorized:
            raise AssertionError("Research candidate cannot be pre-authorized")
        # Private pack contains reference identities and metadata, never stats
        # or CDB record bytes. Names/IDs must NOT appear in public CI logs.
        row = {
            "source_family": family,
            "review_bucket": review.bucket,
            "priority": review.priority,
            "blockers": list(review.blockers),
            "source": _event_payload(source),
            "old_candidate_refs": [_event_payload(e) for e in old[:25]],
            "new_candidate_refs": [
                {"canonical_event_id": n.canonical_event_id,
                 "context_tier": n.context_tier,
                 "research_evidence": list(n.evidence)}
                for n in new[:25]
            ],
            "candidate_list_truncated": len(old) > 25 or len(new) > 25,
            "independent_canonical_identity_attested": False,
            "cdb_import_authorized": False,
        }
        key = (review.priority, family, source.event_id)
        self._rows.append((key,row))
        if len(self._rows) > 2 * self.max_items:
            self._rows.sort(key=lambda v:v[0])
            del self._rows[self.max_items:]

    @property
    def selected(self) -> list[dict]:
        return [x[1] for x in sorted(self._rows,key=lambda v:v[0])[:self.max_items]]

    def write_private(self, output: Path) -> dict:
        """Single-use O_EXCL 0600 output under PRIVATE 0700 parent; forbidden CI."""
        if os.environ.get("CI") or os.environ.get("GITHUB_ACTIONS"):
            raise PermissionError("Private reviewer export is forbidden in CI")
        output = Path(output)
        if not output.name.endswith(".jsonl"):
            raise ValueError("Private reviewer output needs .jsonl extension")
        parent = output.parent.resolve(strict=True)
        if not parent.is_dir():
            raise ValueError("Private reviewer destination must be a directory")
        if stat.S_IMODE(parent.stat().st_mode) & 0o077:
            raise PermissionError("Private reviewer destination must be mode 0700")
        cwd = Path.cwd().resolve()
        if parent == cwd or cwd in parent.parents:
            raise PermissionError("Never save private reviewer pack inside repository")
        result_path = parent / output.name
        records = self.selected
        if not records:
            raise ValueError("No risk cases to export")
        manifest = {
            "schema": "BLINQ_LOCAL_PRIVATE_REVIEW_PACK_V1",
            "kind": "research_only_not_authorized_for_cdb",
            "case_count": len(records),
            "warning": "All candidates require independent player/event/rights/PIT checks.",
        }
        flags = (os.O_WRONLY | os.O_CREAT | os.O_EXCL |
                 getattr(os,"O_NOFOLLOW",0))
        fd=os.open(result_path,flags,0o600)
        try:
            with os.fdopen(fd,"w",encoding="utf-8",newline="\n") as f:
                f.write(json.dumps({"manifest":manifest},sort_keys=True,
                                   ensure_ascii=False)+"\n")
                for row in records:
                    f.write(json.dumps(row,sort_keys=True,
                                       ensure_ascii=False)+"\n")
                f.flush()
                os.fsync(f.fileno())
        except BaseException:
            try:
                result_path.unlink()
            except OSError:
                pass
            raise
        digest=sha256(result_path.read_bytes()).hexdigest()
        buckets=dict(sorted(Counter(r["review_bucket"] for r in records).items()))
        # Metadata-only caller response. Never names, source IDs or CDB IDs.
        return {"written_private": True, "case_count":len(records),
                "priority_bucket_counts":buckets,"sha256":digest,
                "cdb_import_authorized":False}
