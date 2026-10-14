#!/usr/bin/env python3
"""BlinQ identity v2: candidate discovery ONLY. No CDB import or writer access.

Pure, standard-library-only research helpers. An alias, score, name, or even
an exact provider-scoped ID does not attest a canonical cross-provider link.
A separate independently verified crosswalk/rights/PIT/CDB-NULL writer gate
is REQUIRED before any proposed observation can reach canonical storage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from difflib import SequenceMatcher
import re
import unicodedata
from typing import Iterable, Mapping

EXTRA_LATIN = str.maketrans({
    "ł": "l", "đ": "d", "ð": "d", "þ": "th", "ß": "ss",
    "ø": "o", "æ": "ae", "œ": "oe", "ı": "i",
})
CYRILLIC = dict(zip(
    "абвгдежзийклмнопрстуфхцчшщыьъэюяёєїіґ",
    ("a", "b", "v", "g", "d", "e", "zh", "z", "i", "y",
     "k", "l", "m", "n", "o", "p", "r", "s", "t", "u", "f",
     "kh", "ts", "ch", "sh", "shch", "y", "", "", "e",
     "yu", "ya", "yo", "ye", "yi", "i", "g")
))
GREEK = dict(zip(
    "αβγδεζηθικλμνξοπρσςτυφχψω",
    ("a","v","g","d","e","z","i","th","i","k","l","m",
     "n","x","o","p","r","s","s","t","y","f","ch","ps","o")
))
MOJIBAKE = {"Ã¡":"á","Ã©":"é","Ã­":"í","Ã³":"ó",
            "Ãº":"ú","Ã±":"ñ","Ã¼":"ü","Ä":"č",
            "Ä‡":"ć","Å¡":"š","Å¾":"ž","Å‚":"ł"}
ROUND_MAP = {
    "f":"f", "final":"f", "finals":"f",
    "sf":"sf", "semi final":"sf", "semifinal":"sf", "semifinals":"sf",
    "qf":"qf", "quarter final":"qf", "quarterfinal":"qf",
    "rr":"rr", "round robin":"rr", "group":"rr",
    "r16":"r16", "round of 16":"r16", "last 16":"r16",
    "r32":"r32", "round of 32":"r32", "last 32":"r32",
    "r64":"r64", "round of 64":"r64",
    "r128":"r128", "round of 128":"r128",
    "q1":"q1", "qualifying 1":"q1", "qualification round 1":"q1",
    "q2":"q2", "qualifying 2":"q2", "qualification round 2":"q2",
    "q3":"q3", "qualifying 3":"q3", "qualification round 3":"q3",
}
SCORE_SET = re.compile(r"^(?:\[)?(\d{1,2})[-:](\d{1,2})(?:\(\d{1,2}\))?(?:\])?$")
STATUS_TOKENS = {"ret","retired","retirement","wo","w/o","walkover",
                 "def","default","abd","abandoned","unfinished","susp"}
VALID_DATE_KINDS = {"played", "scheduled", "tournament_start", "unknown"}


def latin_text(value: object) -> str:
    """Normalize for SEARCH, with explicit script conversion; never an ID."""
    raw = str(value or "").strip()
    for broken, fixed in MOJIBAKE.items():
        raw = raw.replace(broken, fixed)
    raw = unicodedata.normalize("NFKD", raw.casefold().translate(EXTRA_LATIN))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    raw = "".join(CYRILLIC.get(ch, GREEK.get(ch, ch)) for ch in raw)
    return " ".join(re.findall(r"[^\W_]+", raw, flags=re.UNICODE))


def transliteration_search_key(value: object) -> str:
    """Approximate phonetic ASCII index; RESEARCH ONLY, never exact identity."""
    text = latin_text(value)
    for before,after in (("dzh","dj"),("kh","h"),("zh","z"),
                         ("shch","sc"),("sh","s"),("ch","c"),("ts","c")):
        text = text.replace(before,after)
    return text


def exact_name_key(value: object) -> str:
    return latin_text(value)


def name_keys(value: object) -> frozenset[str]:
    """Broad surname/initial candidate keys; intentionally NOT identity proof.

    Retains all plausible suffixes for compound surnames. Initial-only input
    is indexed in both 'Initial Surname' and 'Surname Initial' order.
    Historical nickname/surname-change associations require curated aliases.
    """
    raw = str(value or "").strip()
    name = exact_name_key(raw)
    if not name:
        return frozenset()
    result = {"exact:" + name, "translit:" + transliteration_search_key(name)}
    tokens = name.split()
    if len(tokens) < 2:
        return frozenset(result)
    forms = []
    if "," in raw:
        before, after = raw.split(",", 1)
        last, first = latin_text(before).split(), latin_text(after).split()
        if last and first:
            forms.append((first, last))
    forms.append((tokens[:-1], tokens[-1:]))  # given name(s) before surname
    # Reversed two-token full names (e.g. DJOKOVIC NOVAK) are discovery-only.
    # Such reversals are ambiguous for East Asian names and NEVER authorize IDs.
    if len(tokens)==2 and all(len(part)>1 for part in tokens):
        forms.append((tokens[1:], tokens[:1]))
    # Compound surname suffixes for 'Botic van de Zandschulp' / 'de Minaur'.
    for i in range(2, min(5, len(tokens))):
        forms.append((tokens[:-i], tokens[-i:]))
    # 'Djokovic N.' / 'Etcheverry T. M.' and 'Sinner, Jannik'.
    trailing = len(tokens)
    while trailing > 0 and len(tokens[trailing-1]) == 1:
        trailing -= 1
    if 0 < trailing < len(tokens):
        forms.append((tokens[trailing:], tokens[:trailing]))
    if len(tokens[0]) == 1 and len(tokens[-1]) > 1:
        forms.append(([tokens[0]], tokens[1:]))
    for given, surname in forms:
        if not given or not surname:
            continue
        initials = "".join(x[0] for x in given)
        last = " ".join(surname)
        if initials and last and last != initials:
            result.add("initials:" + initials + "|" + last)
            # Short initials are discovery-only and collision-prone.
            result.add("initials:" + initials[:1] + "|" + last)
    return frozenset(result)


def scoped_id(namespace: str, tour: str, identifier: str) -> tuple[str,str,str]:
    fields = (str(namespace).strip().casefold(), str(tour).strip().casefold(),
              str(identifier).strip())
    if not all(fields):
        raise ValueError("Source identity needs provider namespace, tour and native ID")
    return fields


@dataclass(frozen=True)
class Player:
    namespace: str
    tour: str
    native_id: str
    name: str
    aliases: tuple[str,...] = ()
    dob: str = ""
    country: str = ""

    def key(self) -> tuple[str,str,str]:
        return scoped_id(self.namespace, self.tour, self.native_id)

    def names(self) -> frozenset[str]:
        return frozenset(k for n in (self.name, *self.aliases) for k in name_keys(n))


@dataclass(frozen=True)
class Candidate:
    target_key: tuple[str,str,str]
    evidence: tuple[str,...]
    score: float
    identity_verified: bool = False
    cdb_write_authorized: bool = False


def discover_players(source: Player, targets: Iterable[Player],
                     *, fuzzy: bool = True) -> list[Candidate]:
    """Wide candidate generation; IDs from DIFFERENT namespaces never equate."""
    if not source.native_id or not source.namespace or not source.tour:
        raise ValueError("Source-scoped player ID required")
    source_keys = source.names()
    output: list[Candidate] = []
    for target in targets:
        if source.tour.casefold() != target.tour.casefold():
            continue
        evidence: list[str] = []
        if source.key() == target.key():
            evidence.append("same_native_identity")
        common = source_keys & target.names()
        if any(k.startswith("exact:") for k in common):
            evidence.append("normalized_or_curated_alias")
        elif any(k.startswith("initials:") for k in common):
            evidence.append("surname_initial_discovery")
        elif any(k.startswith("translit:") for k in common):
            evidence.append("transliteration_research_only")
        # Keep cross-script provenance even when a coarse surname-initial
        # key was also shared. This is *never* independent identity evidence.
        def script(name: str) -> str:
            for char in name:
                label = unicodedata.name(char, "")
                if "CYRILLIC" in label:
                    return "cyrillic"
                if "GREEK" in label:
                    return "greek"
            return "latin_or_other"
        if common and script(source.name) != script(target.name):
            if "transliteration_research_only" not in evidence:
                evidence.append("transliteration_research_only")
        if (source.dob and target.dob and source.dob != target.dob):
            # DOB conflict never rescued by a name-based key.
            continue
        if source.dob and source.dob == target.dob:
            evidence.append("dob_consistent")
        if source.country and source.country.casefold() == target.country.casefold():
            evidence.append("country_consistent")
        if not any(x in evidence for x in ("same_native_identity",
                     "normalized_or_curated_alias", "surname_initial_discovery",
                     "transliteration_research_only")):
            if fuzzy and len(exact_name_key(source.name)) >= 8:
                ratio = SequenceMatcher(None, exact_name_key(source.name),
                                        exact_name_key(target.name)).ratio()
                if ratio >= 0.90:
                    evidence.append("fuzzy_research_only")
            if "fuzzy_research_only" not in evidence:
                continue
        score = (8.0 if "same_native_identity" in evidence else
                 4.0 if "normalized_or_curated_alias" in evidence else
                 2.0 if "surname_initial_discovery" in evidence else 1.0)
        output.append(Candidate(target.key(), tuple(evidence), score))
    return sorted(output, key=lambda v: (-v.score,v.target_key))


def normalize_round(value: object) -> str:
    text = latin_text(value)
    if not text:
        return ""
    if text in ROUND_MAP:
        return ROUND_MAP[text]
    m = re.fullmatch(r"(?:round of|round|r) (16|32|64|128|256)", text)
    if m:
        return "r" + m.group(1)
    return text


def tournament_key(name: object) -> str:
    """Not a verified edition ID; sponsor/venue aliases need curated registry."""
    return latin_text(name)


@dataclass(frozen=True)
class Score:
    sets: tuple[tuple[int,int], ...]
    status: str
    valid: bool


def parse_score(raw: object) -> Score:
    """Score shape, not a winner/complete-match attestation."""
    tokens = str(raw or "").strip().split()
    sets: list[tuple[int,int]] = []
    statuses: list[str] = []
    if not tokens:
        return Score((), "unknown", False)
    for token in tokens:
        stripped = token.strip(".,;").casefold()
        if stripped in STATUS_TOKENS:
            statuses.append(stripped)
            continue
        found = SCORE_SET.fullmatch(token)
        if not found:
            return Score(tuple(sets), "unparsed", False)
        first, second = int(found.group(1)), int(found.group(2))
        if first > 99 or second > 99:
            return Score(tuple(sets), "unparsed", False)
        sets.append((first, second))
    if not sets and not statuses:
        return Score((), "unparsed", False)
    return Score(tuple(sets), " ".join(statuses) if statuses else "score_only", True)


@dataclass(frozen=True)
class Event:
    namespace: str
    event_id: str
    tour: str
    discipline: str
    players: tuple[Player,Player]
    event_date: str
    date_kind: str
    tournament: str
    round_name: str = ""
    score: str = ""
    winner_native_id: str = ""
    edition_id: str = ""
    draw: str = ""

    def __post_init__(self):
        if self.date_kind not in VALID_DATE_KINDS:
            raise ValueError("Explicit event date semantics required")
        # Two athletes model singles only. Doubles need verified 4-player team
        # identity rather than silently treating teams as single players.
        if self.discipline.casefold()!="singles":
            raise ValueError("Doubles/mixed not yet supported by v2 player-pair research adapter")
        if len(self.players) != 2:
            raise ValueError("Two player sides required")
        if any(p.namespace != self.namespace or not p.native_id for p in self.players):
            raise ValueError("Event participants must have native IDs in event namespace")
        if self.players[0].key() == self.players[1].key():
            raise ValueError("A match cannot contain the same native player twice")
        if self.players[0].tour.casefold() != self.tour.casefold() or (
                self.players[1].tour.casefold() != self.tour.casefold()):
            raise ValueError("Tour/player mismatch")


@dataclass(frozen=True)
class EventCandidate:
    canonical_event_id: str
    evidence: tuple[str,...]
    identity_verified: bool = False
    cdb_write_authorized: bool = False
    # Context strength is NOT an independent canonical identity witness.
    context_tier: str = "unresolved_event_edition"


def _day(value: str) -> date | None:
    try:
        return date.fromisoformat(value[:10])
    except (ValueError, TypeError):
        return None


def discover_events(source: Event, canonical: Iterable[Event],
                    *, max_tournament_days: int = 28) -> list[EventCandidate]:
    """For RESEARCH candidates, never evidence of an independently verified CDB ID.

    Always rejects tour/discipline, known draw, mismatching verified-scope
    native IDs (within same namespace), impossible date and winner conflicts.
    Missing round/score/tournament lowers evidence but permits discovery.
    """
    if not source.event_id or not source.namespace:
        raise ValueError("Provider-scoped source event ID required")
    result: list[EventCandidate] = []
    source_day = _day(source.event_date)
    if source_day is None:
        # Zero dates on both sides must never manufacture a link.
        # Invalid/missing dates are candidates for source normalization review,
        # not a valid match-discovery time window.
        return []
    source_names = [x.names() for x in source.players]
    for event in canonical:
        if not event.event_id or (source.tour.casefold(),source.discipline.casefold()) != (
                event.tour.casefold(),event.discipline.casefold()):
            continue
        if source.draw and event.draw and source.draw.casefold() != event.draw.casefold():
            continue
        if source.edition_id and event.edition_id and (
                source.namespace==event.namespace and source.edition_id != event.edition_id):
            continue
        alternatives = []
        for sides in ((0,1),(1,0)):
            good=True;ev=[]
            for idx,side in enumerate(sides):
                src=source.players[idx];dst=event.players[side]
                if src.key()==dst.key():
                    ev.append("same_provider_native_id")
                elif src.namespace==dst.namespace and src.native_id==dst.native_id and src.tour==dst.tour:
                    ev.append("same_provider_native_id")
                elif src.namespace==dst.namespace and src.native_id!=dst.native_id:
                    good=False;break
                elif source_names[idx] & dst.names():
                    ev.append("alias_pair_research")
                else:
                    good=False;break
            if good:
                alternatives.append((sides,ev))
        if len(alternatives)!=1:
            continue  # ambiguous orientation and self-matches fail closed
        sides,evidence=alternatives[0]
        target_day=_day(event.event_date)
        if target_day is None:
            continue
        if source_day and target_day:
            days=(target_day-source_day).days
            if source.date_kind=="tournament_start" and event.date_kind in ("scheduled","played"):
                if not 0 <= days <= max_tournament_days:
                    continue
                evidence.append("tournament_start_window")
            elif abs(days) > 1:
                continue
            else:
                evidence.append("near_match_day")
        elif source_day != target_day:
            continue
        sr,cr=normalize_round(source.round_name),normalize_round(event.round_name)
        if sr and cr and sr != cr:
            continue
        if sr and cr:
            evidence.append("round")
        if source.edition_id and event.edition_id and (
                source.namespace == event.namespace and source.edition_id == event.edition_id):
            evidence.append("same_source_edition")
        elif tournament_key(source.tournament)==tournament_key(event.tournament) and (
                tournament_key(source.tournament)):
            evidence.append("tournament_label")
        else:
            # Keep broad recall in RESEARCH. A different event name can mean
            # the same event with a sponsor alias OR a different tournament.
            # Without an edition alias registry it is not a strong event link.
            evidence.append("tournament_edition_unresolved")
        # Player-side winner consistency does not require the native player ID
        # *values* to be comparable across sources. The pair orientation above
        # provides research-only matching of sides, never cross-provider proof.
        if source.winner_native_id and event.winner_native_id:
            sw=next((idx for idx,p in enumerate(source.players)
                     if p.native_id==source.winner_native_id),None)
            cw=next((idx for idx,p in enumerate(event.players)
                     if p.native_id==event.winner_native_id),None)
            if sw is None or cw is None or sides[sw]!=cw:
                continue
            evidence.append("winner_orientation_research")
        if source.score and event.score:
            ss,cs=parse_score(source.score),parse_score(event.score)
            if ss.valid and cs.valid:
                if (ss.status=="score_only") != (cs.status=="score_only"):
                    continue  # cannot silently equate a retirement with a completion
                if ss.status=="score_only":
                    desired=ss.sets if sides==(0,1) else tuple((b,a) for a,b in ss.sets)
                    if desired != cs.sets:
                        continue
                    evidence.append("score_shape")
        context_tier = (
            "edition_context_strong"
            if ("tournament_label" in evidence or "same_source_edition" in evidence)
            and "round" in evidence
            and "winner_orientation_research" in evidence
            else "unresolved_event_edition"
        )
        result.append(EventCandidate(event.event_id,tuple(evidence),
                                     context_tier=context_tier))
    return sorted(result,key=lambda x:(x.context_tier!="edition_context_strong",
                                       -len(x.evidence),x.canonical_event_id))


def no_write_contract(candidates: Iterable[Candidate | EventCandidate]) -> bool:
    """Sanity check that this entire research layer never authorizes CDB writes."""
    return all(not c.identity_verified and not c.cdb_write_authorized for c in candidates)
