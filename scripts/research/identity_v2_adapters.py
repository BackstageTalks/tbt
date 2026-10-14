"""Source-native, read-only event adapters for BlinQ identity-v2 research.

All adapters keep provider IDs scoped and never validate rights, corroborate
canonical identities, or create CDB import batches. Unusable partial inputs are
quarantined as data, not silently inferred from names, URLs or placeholders.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
import json
import re
from typing import Mapping, Callable

from scripts.research.identity_v2 import Event, Player

NAMESPACE = re.compile(r"^[a-zA-Z0-9:_./-]{3,160}$")
DATE_YYYYMMDD = re.compile(r"^\d{8}$")
STAT_FIELDS = ("aces", "double_faults", "service_points", "first_serve_in",
               "first_serve_won", "second_serve_won", "break_points_saved",
               "break_points_faced")


@dataclass(frozen=True)
class Adapted:
    event: Event | None
    source_namespace: str
    source_native_key: str
    reasons: tuple[str, ...] = ()
    research_only: bool = True
    cdb_import_authorized: bool = False


def _text(obj: object) -> str:
    return str(obj or "").strip()


def _date(raw: object, *, yyyymmdd: bool = False) -> str:
    if isinstance(raw,datetime):
        return raw.date().isoformat()
    if isinstance(raw,date):
        return raw.isoformat()
    val=_text(raw)
    if yyyymmdd and DATE_YYYYMMDD.fullmatch(val):
        try:
            return datetime.strptime(val,"%Y%m%d").date().isoformat()
        except ValueError:
            return ""
    if re.fullmatch(r"\d{4}-\d\d-\d\d",val[:10]):
        try:
            return date.fromisoformat(val[:10]).isoformat()
        except ValueError:
            return ""
    return ""


def namespace(source: str, category: str) -> str:
    text=(source+":"+category).strip()
    if not NAMESPACE.fullmatch(text):
        raise ValueError("Invalid scoped upstream namespace")
    return text


def _stage(ns: str, tour: str, p1_id: str, p1_name: str,
           p2_id: str, p2_name: str, match_id: str, when: str,
           date_kind: str, tournament: str, round_name: str="",
           winner_id: str="", score: str="", draw: str="",
           edition_id: str="") -> Adapted:
    if not all((ns,tour,match_id,when,p1_id,p2_id,p1_name,p2_name)):
        return Adapted(None,ns,match_id,("incomplete_source_native_event",))
    if p1_id==p2_id:
        return Adapted(None,ns,match_id,("source_player_id_collision",))
    if winner_id and winner_id not in (p1_id,p2_id):
        return Adapted(None,ns,match_id,("source_winner_id_outside_pair",))
    try:
        event=Event(ns,match_id,tour,"singles",
            (Player(ns,tour,p1_id,p1_name),Player(ns,tour,p2_id,p2_name)),
            when,date_kind,tournament,round_name,score,winner_id,
            edition_id=edition_id,draw=draw)
    except ValueError:
        return Adapted(None,ns,match_id,("invalid_event_contract",))
    return Adapted(event,ns,match_id)


def from_sackmann(row: Mapping[str,object], *, tour: str, collection: str,
                  file_sha256: str, line_number: int) -> Adapted:
    """Sackmann source tournament-start date, winner/loser, never CDB IDs."""
    if tour not in ("atp","wta"):
        raise ValueError("Tour must be explicitly ATP or WTA")
    if not re.fullmatch(r"[0-9a-f]{64}",file_sha256) or line_number<2:
        raise ValueError("File provenance SHA and source CSV line required")
    ns=namespace("sackmann",tour+"_"+collection)
    when=_date(row.get("tourney_date"),yyyymmdd=True)
    # Source match_num alone collides; line is a source-row coordinate,
    # NEVER an authoritative provider event ID.
    native=f"{file_sha256[:16]}:{line_number}"
    return _stage(ns,tour,_text(row.get("winner_id")),_text(row.get("winner_name")),
        _text(row.get("loser_id")),_text(row.get("loser_name")),
        native,when,"tournament_start",_text(row.get("tourney_name")),
        _text(row.get("round")),_text(row.get("winner_id")),
        _text(row.get("score")),
        "qual" if "qual" in collection else "",
        edition_id=_text(row.get("tourney_id")))


def from_season(row: Mapping[str,object], *, tour: str,
                collection: str, file_sha256: str, line_number: int) -> Adapted:
    """L2/TennisData source-native fields; ambiguous display name never IDs."""
    if tour not in ("atp","wta"):
        raise ValueError("Explicit tour required")
    if not re.fullmatch(r"[a-f0-9]{64}",file_sha256) or line_number<2:
        raise ValueError("File provenance required")
    ns=namespace("season",tour+"_"+collection)
    source_mid=_text(row.get("match_id")) or f"{file_sha256[:16]}:{line_number}"
    when=_date(row.get("start_time_utc") or row.get("date") or row.get("tourney_date"),
               yyyymmdd=bool(DATE_YYYYMMDD.fullmatch(_text(row.get("tourney_date")))))
    date_kind=("scheduled" if row.get("start_time_utc") else
               "tournament_start" if row.get("tourney_date") and not row.get("date") else "played")
    return _stage(ns,tour,
        _text(row.get("home_id") or row.get("player1_id") or row.get("winner_id")),
        _text(row.get("home") or row.get("player1_name") or row.get("winner_name")),
        _text(row.get("away_id") or row.get("player2_id") or row.get("loser_id")),
        _text(row.get("away") or row.get("player2_name") or row.get("loser_name")),
        source_mid,when,date_kind,
        _text(row.get("tournament") or row.get("tourney_name")),
        _text(row.get("round")),
        _text(row.get("winner_id")),
        _text(row.get("score")),
        edition_id=_text(row.get("tourney_id") or row.get("tournament_id")))


def from_cdb_metadata(row: Mapping[str,object]) -> Adapted:
    """Treat canonical metadata as comparator context, not writable CDB data."""
    ns="cdb:canonical"
    tour=_text(row.get("tour")).casefold()
    if tour not in ("atp","wta"):
        return Adapted(None,ns,_text(row.get("match_id")),("out_of_scope_tour",))
    when=_date(row.get("scheduled_at"))
    return _stage(ns,tour,_text(row.get("player1_id")),
        _text(row.get("player1_name")),_text(row.get("player2_id")),
        _text(row.get("player2_name")),_text(row.get("match_id")),
        when,"scheduled",_text(row.get("tournament")),
        _text(row.get("round_name")),_text(row.get("winner_id")))


def require_source_only(record: Adapted) -> Adapted:
    if record.cdb_import_authorized or not record.research_only:
        raise ValueError("Adapter must NEVER authorize a canonical CDB mutation")
    return record


def parse_nonnegative_int(value: object) -> int | None:
    """Null is missing, numeric 0 is observed zero, NaN and booleans invalid."""
    if value is None:
        return None
    if isinstance(value,bool):
        raise ValueError("Boolean cannot be a count")
    if isinstance(value,int) and value>=0:
        return value
    if isinstance(value,str):
        txt=value.strip()
        if not txt or txt.casefold() in ("nan","none","null","n/a"):
            return None
        if re.fullmatch(r"[0-9]+",txt):
            return int(txt)
    raise ValueError("Unverifiable count")
