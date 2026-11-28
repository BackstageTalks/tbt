"""Pre-match rules and validation of completed singles scorelines."""
from dataclasses import dataclass
from datetime import datetime
import re


@dataclass(frozen=True)
class Rules:
    match_tiebreak: bool = False
    short: bool = False
    no_ad: bool = False


STANDARD = Rules()


def rules_for(m):
    override = (m.provider_payload or {}).get("scoring_rules")
    if override is not None:
        if not isinstance(override, dict) or not override.get("source"):
            return None
        try:
            issued = datetime.fromisoformat(override["as_of"])
            fields = [override[k] for k in ("match_tiebreak","short","no_ad")]
        except (ValueError, KeyError, TypeError):
            return None
        if not issued.tzinfo or issued >= m.scheduled_at or any(type(v) is not bool for v in fields):
            return None
        return Rules(*fields)
    name = (m.tournament or "").lower()
    level = (m.tournament_level or "").lower()
    if "next gen" in name and "final" in name:
        return Rules(short=True, no_ad=True)
    if "itf" in level:
        if not m.round_name:
            return None
        if "qual" in m.round_name.lower():
            if m.tour.lower() == "atp" or re.search(r"\bw(?:15|25|35)\b", name):
                return Rules(match_tiebreak=True)
            if not re.search(r"\bw(?:50|60|75|80|100)\b", name):
                return None
    return STANDARD


def completed_set(a, b, short):
    hi, lo = max(a,b), min(a,b)
    return (hi == 4 and lo <= 3) if short else (
        (hi == 6 and lo <= 4) or (hi == 7 and lo in (5,6)))


def score_audit(m, best, rules):
    reason = (m.provider_payload.get("_tbt_termination") or {}).get("reason")
    if reason or not m.is_completed or m.status.lower() not in ("finished","completed","ended","ft","final"):
        return reason or "unfinished", None
    if not rules or best not in (3,5):
        return "unknown_format", None
    s = m.stats
    def integer(key):
        v = s.get(key)
        return int(v) if type(v) in (float,int) and v >= 0 and v < 500 and int(v)==v else None
    count = integer("total_sets")
    wins = [integer(f"p{i}_sets_won") for i in (1,2)]
    games = [integer(f"p{i}_games_won") for i in (1,2)]
    if None in [count,*wins,*games,integer("total_games")]:
        return "incomplete", None
    if sum(games)!=integer("total_games") or sum(wins)!=count or max(wins)!=best//2+1 or count>best:
        return "inconsistent_summary", None
    tally, used = [0,0], [0,0]
    normalized = [0,0]
    for index in range(1,count+1):
        pair = [integer(f"p{i}_set{index}_games") for i in (1,2)]
        if index == count and index >= 3 and pair == [None,None]:
            pair = [g-u for g,u in zip(games,used)]
        if None in pair:
            return "incomplete", None
        a,b = pair
        if min(pair)<0 or a==b or max(tally)==best//2+1:
            return "unfinished_score", None
        win = int(b>a)
        if rules.match_tiebreak and index==best:
            hi,lo=max(pair),min(pair)
            if sorted(pair)!=[0,1] and not (hi==10 and lo<=8 or hi>10 and hi-lo==2):
                return "decider_format_conflict", None
            normalized[win]+=1
        else:
            if not completed_set(a,b,rules.short):
                return "unfinished_or_format_conflict", None
            for i in (0,1):
                normalized[i]+=pair[i]
        tally[win]+=1
        for i in (0,1):
            used[i]+=pair[i]
    if any((integer(f"p{side}_set{idx}_games") or 0) > 0
           for idx in range(count+1,6) for side in (1,2)):
        return "extra_period", None
    # Some sources retain the tiebreak points in the set but settle aggregate
    # games at 1:0; others sum the raw point score. Accept either coherent pair.
    if (used!=games and normalized!=games) or tally!=wins or ((wins[0]>wins[1]) != (m.winner_id==m.player1_id)):
        return "inconsistent_summary", None
    return "complete", tuple(normalized)


def calibration_level(m):
    from .point_model import competition
    level = competition(m)
    if level == "ITF":
        return "ITF M" if m.tour.lower() == "atp" else "ITF W"
    return level
