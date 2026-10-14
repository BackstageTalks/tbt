"""Source-scoped, research-only tournament edition registry for BlinQ Identity V2.

An edition proposal is NOT an independent provider-issued tournament bridge.
This module is isolated from CDB writers and cannot grant canonical identity
or import rights. Explicit source edition IDs are required: names, cities,
sponsor labels and year proximity alone only produce review candidates.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable

from scripts.research.identity_v2 import latin_text

_SHA = re.compile(r"^[0-9a-f]{64}$")
_ALLOWED = {"atp", "wta"}
_DRAWS = {"main", "qual", "round_robin", "unknown"}
_LEVELS = {"tour", "challenger", "itf", "futures", "grand_slam",
           "olympics", "team", "junior", "other", "unknown"}
_DISCIPLINES = {"singles", "doubles", "mixed"}


@dataclass(frozen=True)
class EditionRecord:
    """Untrusted research metadata, not an independently verified CDB witness."""
    source_namespace: str
    native_edition_id: str
    tour: str
    season: int
    draw: str
    discipline: str
    level: str
    research_edition_key: str
    tournament_name: str
    source_file_sha256: str
    aliases: tuple[str, ...] = ()
    reference: str = ""

    def __post_init__(self) -> None:
        if not self.source_namespace or not self.native_edition_id:
            raise ValueError("Source namespace and source-issued edition ID required")
        if self.tour not in _ALLOWED or self.discipline not in _DISCIPLINES:
            raise ValueError("Invalid tour/discipline")
        if self.draw not in _DRAWS or self.level not in _LEVELS:
            raise ValueError("Invalid draw/level")
        if not (1877 <= self.season <= 2100):
            raise ValueError("Explicit plausible edition season required")
        if not self.research_edition_key or not self.tournament_name:
            raise ValueError("Research edition key and raw name required")
        if _SHA.fullmatch(self.source_file_sha256) is None:
            raise ValueError("SHA-pinned original source required")
        if not self.reference:
            raise ValueError("Provenance reference required")

    @property
    def source_key(self) -> tuple[str, str, str, int, str, str, str]:
        return (self.source_namespace.casefold(), self.native_edition_id,
                self.tour, self.season, self.draw, self.discipline, self.level)

    @property
    def strict_context(self) -> tuple[str, int, str, str, str]:
        return self.tour, self.season, self.draw, self.discipline, self.level

    def keys(self) -> frozenset[str]:
        return frozenset(latin_text(name) for name in
                         (self.tournament_name, *self.aliases) if latin_text(name))


@dataclass(frozen=True)
class EditionReview:
    source_key: tuple[str, str, str, int, str, str, str]
    proposed_edition_keys: tuple[str, ...]
    status: str
    evidence: tuple[str, ...] = ()
    identity_verified: bool = False
    canonical_event_verified: bool = False
    cdb_write_authorized: bool = False


class ResearchEditionRegistry:
    """Conservative, immutable in-memory registry of unapproved edition claims."""

    def __init__(self, records: Iterable[EditionRecord]) -> None:
        by_source: dict[tuple, list[EditionRecord]] = {}
        by_name: dict[tuple, set[tuple]] = {}
        for record in records:
            by_source.setdefault(record.source_key, []).append(record)
            for alias in record.keys():
                by_name.setdefault((record.strict_context, alias), set()).add(
                    record.source_key)
        self._source = {k: tuple(v) for k, v in by_source.items()}
        self._names = {k: frozenset(v) for k, v in by_name.items()}

    def review(self, record: EditionRecord) -> EditionReview:
        proposals = self._source.get(record.source_key, ())
        keys = tuple(sorted({p.research_edition_key for p in proposals}))
        if not proposals:
            return EditionReview(record.source_key, (), "source_edition_unknown")
        if len(keys) != 1:
            return EditionReview(record.source_key, keys, "source_edition_collision",
                                 ("conflicting_manual_or_source_claims",))
        # A curated research label is *not* a verified official ID bridge.
        return EditionReview(record.source_key, keys[0:1],
                             "research_edition_proposal",
                             ("source_scoped_edition_id", "source_sha_and_reference"))

    def discover_aliases(self, *, name: str, tour: str, season: int,
                         draw: str, discipline: str, level: str) -> tuple[EditionReview, ...]:
        """Name discovery requires ALL edition scoping dimensions.

        Sponsor/translation aliases remain RESEARCH_ONLY, even when unique.
        """
        if (tour not in _ALLOWED or draw not in _DRAWS or
                level not in _LEVELS or discipline not in _DISCIPLINES):
            raise ValueError("Exact tournament scoping required")
        context = (tour, season, draw, discipline, level)
        keys = sorted(self._names.get((context, latin_text(name)), ()))
        return tuple(self.review(self._source[k][0]) for k in keys)

    def compare(self, left: EditionRecord, right: EditionRecord) -> str:
        """Only a research verdict. Never sufficient for an event/identity write."""
        if left.strict_context != right.strict_context:
            return "edition_context_conflict"
        a, b = self.review(left), self.review(right)
        if (a.status == "source_edition_collision" or
                b.status == "source_edition_collision"):
            return "edition_claim_collision"
        if a.status != "research_edition_proposal" or (
                b.status != "research_edition_proposal"):
            return "edition_witness_unavailable"
        if a.proposed_edition_keys == b.proposed_edition_keys:
            return "same_research_edition_proposal"
        # Distinct manual keys are not a definitive hard-negative without
        # independently checked authoritative edition identity.
        return "different_research_edition_proposals"


def no_write_contract(items: Iterable[EditionReview]) -> bool:
    return all(not x.identity_verified and not x.canonical_event_verified
               and not x.cdb_write_authorized for x in items)
