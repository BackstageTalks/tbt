"""Conservative BlinQ Comeback LIVE Radar."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
import math, os
from typing import Any
from .admin_storage import save_automated_insight

DEFAULT_MIN_PROBABILITY=.78
DEFAULT_MAX_ODDS=1.35
LIVE_ALERT_LEVELS=['elite','legend','goat']

def _num(v):
    try:n=float(v)
    except (TypeError,ValueError):return None
    return n if math.isfinite(n) else None

def _int(v):
    n=_num(v)
    return int(round(n)) if n is not None and abs(n-round(n))<1e-9 else None

def radar_thresholds():
    def ev(name,default):
        n=_num(os.getenv(name)); return float(n) if n is not None else default
    return {'min_probability':min(.99,max(.5,ev('BLINQ_LIVE_RADAR_MIN_PROBABILITY',DEFAULT_MIN_PROBABILITY))),
            'max_odds':min(1.49,max(1.01,ev('BLINQ_LIVE_RADAR_MAX_ODDS',DEFAULT_MAX_ODDS)))}

def _selection(row):
    b=row.get('betting') if isinstance(row.get('betting'),dict) else {}
    return str(b.get('selection_id') or row.get('winner_id') or '').strip(), str(b.get('selection') or row.get('pick') or '').strip()

def _probability(row):
    b=row.get('betting') if isinstance(row.get('betting'),dict) else {}
    for v in (b.get('blinq_probability'),row.get('blinq_probability'),b.get('model_probability'),row.get('raw_model_probability'),row.get('confidence'),row.get('probability')):
        n=_num(v)
        if n is not None:return n/100 if n>1 else n
    vals=[]
    for k in ('player1','player2'):
        p=row.get(k) if isinstance(row.get(k),dict) else {}; n=_num(p.get('probability'))
        if n is not None:vals.append(n/100 if n>1 else n)
    return max(vals,default=0.)

def _odds(row):
    b=row.get('betting') if isinstance(row.get('betting'),dict) else {}
    for v in (b.get('odds'),row.get('odds')):
        n=_num(v)
        if n is not None and n>1:return n
    return None

def prime_radar_eligible(row: dict) -> bool:
    """Cheap prefilter used before any live-provider request."""
    th=radar_thresholds(); p=_probability(row); odds=_odds(row)
    return bool(p+1e-12>=th['min_probability'] and odds is not None and odds<=th['max_odds']+1e-12)

def _event_id(e):return str(e.get('id') or e.get('eventId') or e.get('event_id') or '').strip()
def _team(e,k):return e.get(k) if isinstance(e.get(k),dict) else {}
def _score(e,k):return e.get(k) if isinstance(e.get(k),dict) else {}
def _set_score(e,p):return _int(_score(e,'homeScore').get(f'period{p}')),_int(_score(e,'awayScore').get(f'period{p}'))
def _winner(pair):
    h,a=pair
    if h is None or a is None or h==a:return ''
    hi,lo=max(h,a),min(h,a); complete=(hi==6 and lo<=4) or (hi==7 and lo in {5,6})
    if not complete:return ''
    return 'home' if h>a else 'away'
def _side_pair(pair,side):
    h,a=pair;return (h,a) if side=='home' else (a,h)
def _favorite_side(e,row):
    hid,aid=str(_team(e,'homeTeam').get('id') or ''),str(_team(e,'awayTeam').get('id') or '')
    sid,sname=_selection(row)
    if sid and sid==hid:return 'home'
    if sid and sid==aid:return 'away'
    sn=' '.join(sname.casefold().split()); hn=' '.join(str(_team(e,'homeTeam').get('name') or '').casefold().split()); an=' '.join(str(_team(e,'awayTeam').get('name') or '').casefold().split())
    if sn and sn==hn:return 'home'
    if sn and sn==an:return 'away'
    return ''
def _name(e,side):return str(_team(e,'homeTeam' if side=='home' else 'awayTeam').get('name') or '').strip()
def _opp(e,side):return str(_team(e,'awayTeam' if side=='home' else 'homeTeam').get('name') or '').strip()

@dataclass
class RadarCandidate:
    event_id:str; favorite:str; opponent:str; probability:float; odds:float|None; first_set:str; second_set:str; stage:str; trigger:bool; reason:str; tournament:str=''
    def public(self):return asdict(self)

def evaluate_prime_live(row,event,*,min_probability,max_odds):
    p=_probability(row); odds=_odds(row)
    if p+1e-12<min_probability or odds is None or odds>max_odds+1e-12:return None
    side=_favorite_side(event,row)
    if not side:return None
    first=_set_score(event,1); fw=_winner(first)
    if not fw or fw==side:return None
    second=_set_score(event,2); fav2,opp2=_side_pair(second,side); sw=_winner(second)
    trigger=False; stage='watch'; reason='favorite_lost_first_set'
    if sw==side:trigger=True;stage='second_set_won';reason='favorite_won_second_set'
    elif fav2 is not None and opp2 is not None and fav2>=3 and fav2-opp2>=2:trigger=True;stage='break_lead';reason='favorite_has_break_lead_in_second_set'
    ff,fo=_side_pair(first,side); t=event.get('tournament') if isinstance(event.get('tournament'),dict) else {}
    return RadarCandidate(_event_id(event) or str(row.get('event_id') or ''),_name(event,side),_opp(event,side),p,odds,'—' if ff is None or fo is None else f'{ff}:{fo}','—' if fav2 is None or opp2 is None else f'{fav2}:{opp2}',stage,trigger,reason,str(t.get('name') or row.get('tournament') or '').strip())

def scan_comeback_radar(feed,live_events):
    th=radar_thresholds(); prime=feed.get('prime_picks') if isinstance(feed.get('prime_picks'),list) else []; live={_event_id(e):e for e in live_events if isinstance(e,dict) and _event_id(e)}; candidates=[]
    for row in prime:
        if not isinstance(row,dict):continue
        e=live.get(str(row.get('event_id') or '').strip())
        if not e:continue
        status=e.get('status') if isinstance(e.get('status'),dict) else {}; st=str(status.get('type') or status.get('description') or e.get('status') or '').lower()
        if st in {'finished','ended','canceled','cancelled','postponed'}:continue
        c=evaluate_prime_live(row,e,**th)
        if c:candidates.append(c)
    signals=[c for c in candidates if c.trigger]
    return {'scanned_at':datetime.now(timezone.utc).isoformat(),'live_events':len(live_events),'prime_pool':len(prime),'candidates':[c.public() for c in candidates],'signals':[c.public() for c in signals],'thresholds':th}

def publish_radar_signals(scan,*,actor_id='live-radar'):
    published=[]
    for s in scan.get('signals',[]):
        eid=str(s.get('event_id') or '').strip()
        if not eid:continue
        fav=str(s.get('favorite') or 'Favorit'); opp=str(s.get('opponent') or ''); p=_num(s.get('probability')) or 0; odds=_num(s.get('odds')); stage=str(s.get('stage') or ''); ss=str(s.get('second_set') or '—')
        body=(f'{fav} prehral 1. set, ale vyrovnal zápas na sety. BlinQ comeback profil zostáva silný.' if stage=='second_set_won' else f'{fav} prehral 1. set a v 2. sete má break náskok ({ss}). BlinQ comeback podmienky sú splnené.')
        if opp:body+=f' Súper: {opp}.'
        body+=f' Predzápasová pravdepodobnosť {p*100:.1f}%'+(f', pôvodný kurz {odds:.2f}.' if odds is not None else '.')
        item,created=save_automated_insight({'title':f'Comeback LIVE · {fav}','body':body,'type':'alert','priority':'important','levels':LIVE_ALERT_LEVELS,'match_id':eid,'link_label':'Otvoriť zápas','active':True,'pinned':False},actor_id=actor_id,insight_id=f'live-comeback-{eid}'[:96])
        published.append({'id':item.get('id'),'event_id':eid,'created':created})
    return {'published':published,'created':sum(1 for x in published if x['created'])}
