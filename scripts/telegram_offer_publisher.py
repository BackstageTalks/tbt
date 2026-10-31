"""Read confirmed BlinQ offer and publish through Telegram without paid APIs."""
import argparse, hashlib, json, os, re, subprocess, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from tbt.services.entitlements import _daily_rows
TZ=ZoneInfo("Europe/Bratislava")
SECTIONS={"top":"top_daily_picks","value":"value_picks","aces":"ace_picks"}
LABELS={"top":"🏆 TOP","value":"💎 VALUE","aces":"🎯 ESÁ"}
def load(p): return json.loads(Path(p).read_text(encoding="utf-8"))
def save(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
def stamp(v):
    d=datetime.fromisoformat(str(v).replace("Z","+00:00"))
    if d.tzinfo is None: raise ValueError("Timezone required")
    return d.astimezone(timezone.utc)
def day(d):
    x=d.astimezone(TZ)
    return (x-timedelta(days=1) if x.hour<6 else x).date().isoformat()
def config(url):
    if not re.fullmatch(r"https://[A-Za-z0-9.-]+/api/v1/ui-config",url): raise ValueError("Invalid endpoint")
    with urllib.request.urlopen(url,timeout=20) as f: data=f.read(1000001)
    if len(data)>1000000: raise ValueError("Oversize config")
    x=json.loads(data)
    if x.get("storage_available") is not True or x.get("runtime_configured") is not True: raise RuntimeError("Unverified live Admin config")
    v=(x.get("config") or {}).get("telegram_bot") or {}
    s=v.get("schedule") or {}; cats=v.get("sections") or {}
    if not isinstance(v,dict) or not isinstance(s,dict) or not isinstance(cats,dict): raise ValueError("Invalid configuration")
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d",str(s.get("time","08:15"))): raise ValueError("Invalid clock")
    if any(type(cats.get(k,False)) is not bool for k in SECTIONS): raise ValueError("Invalid categories")
    if type(v.get("max_per_section",7)) is not int or not 1<=v.get("max_per_section",7)<=10: raise ValueError("Invalid limit")
    if v.get("layout","combined") not in ("combined","separate"): raise ValueError("Invalid layout")
    if not isinstance(s.get("weekdays",list(range(7))),list) or any(type(n) is not int or n not in range(7) for n in s.get("weekdays",list(range(7)))): raise ValueError("Invalid weekdays")
    for f in ("enabled","include_started","show_probability","show_odds","free_top_pick"):
        if type(v.get(f,False)) is not bool: raise ValueError("Invalid "+f)
    if type(s.get("enabled",False)) is not bool: raise ValueError("Invalid schedule enabled")
    return v
def due(v,now):
    if not v.get("enabled") or not (any((v.get("sections") or {}).get(k) for k in SECTIONS) or v.get("free_top_pick",True)): return None
    r=v.get("manual_request") or {}
    if isinstance(r,dict) and re.fullmatch("[A-Za-z0-9_-]{8,80}",str(r.get("id",""))):
        age=(now-stamp(r.get("created_at"))).total_seconds()
        if 0<=age<=5400 and day(stamp(r["created_at"]))==day(now): return "manual:"+r["id"]
    s=v.get("schedule") or {};local=now.astimezone(TZ)
    if not s.get("enabled"): return None
    h,m=map(int,s.get("time","08:15").split(":"));planned=local.replace(hour=h,minute=m,second=0,microsecond=0)
    # Accept the prior local calendar day's late schedule after midnight.
    if planned>local:planned-=timedelta(days=1)
    if planned.weekday() not in s.get("weekdays",list(range(7))):return None
    if day(planned)==day(now) and 0<=(local-planned).total_seconds()<=5400: return "schedule:"+day(now)
    return None
def snapshot(dest):
    dest=Path(dest);dest.mkdir(parents=True,exist_ok=True)
    for file in ("_tbt_bundle_manifest.json","daily_offer_snapshot.json"):
        subprocess.run(["gh","release","download","tbt-predictions-v1","--repo","BackstageTalks/tbt-data","--pattern",file,"--dir",str(dest),"--clobber"],check=True)
    m=(load(dest/"_tbt_bundle_manifest.json").get("files") or {}).get("daily_offer_snapshot.json") or {}
    data=(dest/"daily_offer_snapshot.json").read_bytes()
    if len(data)>12000000 or m.get("bytes")!=len(data) or hashlib.sha256(data).hexdigest()!=m.get("sha256"): raise RuntimeError("Verified snapshot digest mismatch")
    x=json.loads(data)
    if x.get("confirmed_only") is not True: raise RuntimeError("Unconfirmed offer")
    return x
def num(v):
    try: return float(v) if v is not None else None
    except (TypeError,ValueError): return None
NUMBER_EMOJIS=("1️⃣","2️⃣","3️⃣","4️⃣","5️⃣","6️⃣","7️⃣","8️⃣","9️⃣","🔟")
HEADER="Data Betting by BackstageTalks"
FOOTER="ℹ️ Analytical preview only\n🧠 by BackstageTalks Data Engine"
def _selection_name(row):
    bet=row.get("betting") or {}
    sid=str(bet.get("selection_id") or row.get("selection_id") or row.get("winner_id") or "")
    for player in (row.get("player1") or {},row.get("player2") or {}):
        if str(player.get("id"))==sid and player.get("name"):
            return str(player["name"]).strip()
    return str(row.get("pick") or row.get("selection") or sid).strip()

def _name_map(rows):
    # Preserve compact surname-style Telegram names while disambiguating collisions.
    names=list(dict.fromkeys(_selection_name(row) for row in rows))
    surnames={}
    for full in names:
        surname=full.split()[-1] if full.split() else "—"
        surnames.setdefault(surname.casefold(),[]).append(full)
    names_out={}
    for full in names:
        parts=full.split()
        surname=parts[-1] if parts else "—"
        if len(surnames[surname.casefold()])>1 and len(parts)>1:
            initials="".join(item[:1].upper()+"." for item in parts[:-1])
            names_out[full]=initials+" "+surname
        else:
            names_out[full]=surname
    # Shared initials are ambiguous: keep complete names instead.
    used={}
    for full,display in names_out.items():
        used.setdefault(display.casefold(),[]).append(full)
    return {full:(full if len(used[display.casefold()])>1 else display)
            for full,display in names_out.items()}

def fmt(r,k,c,index=1,name_map=None):
    bet=r.get("betting") or {}
    selected=_selection_name(r)
    name=(name_map or {}).get(selected) or selected.split()[-1] if selected else "—"
    time=stamp(r["scheduled_at"]).astimezone(TZ).strftime("%H:%M")
    if k=="aces":
        projection=num(r.get("projection")); confidence=num(r.get("projection_confidence"))
        values=[f"esá {projection:.1f}" if projection is not None else "projekcia —"]
        if confidence is not None:values.append(f"{(confidence*100 if abs(confidence)<=1 else confidence):.1f}%")
    else:
        prob=num(bet.get("blinq_probability") or bet.get("model_probability") or r.get("blinq_probability") or r.get("probability"))
        values=[f"{(prob*100 if abs(prob)<=1 else prob):.1f}%" if prob is not None else "—"] if c.get("show_probability",True) else []
    odds=num(bet.get("odds") or r.get("odds"))
    if c.get("show_odds",True):
        values.append(f"{odds:.2f}" if odds is not None and odds>1 else "—")
    if k=="value":
        ev=num(bet.get("expected_value") if "expected_value" in bet else r.get("expected_value"))
        if ev is not None:values.append(f"EV {(ev*100 if abs(ev)<=1 else ev):+.1f}%")
    prefix=NUMBER_EMOJIS[index-1] if 1<=index<=len(NUMBER_EMOJIS) else f"{index}."
    return f"{prefix} {name} | {time} | "+" | ".join(values)

def select_groups(x,c,now):
    today=day(now)
    generated=stamp(x["generated_at"])
    if x.get("betting_day")!=today or day(generated)!=today or generated>now+timedelta(minutes=5):
        raise RuntimeError("Wrong betting day")
    got={};seen=set()
    for k,key in SECTIONS.items():
        if not (c.get("sections") or {}).get(k) and not (k=="top" and c.get("free_top_pick",True)):
            continue
        source=_daily_rows(x) if k=='top' else (x.get(key) or [])
        if not isinstance(source,list):raise ValueError("Invalid confirmed offer section")
        rows=[]
        for r in source:
            if not isinstance(r,dict) or not r.get("event_id") or (k=="aces" and r.get("market")!="aces"):
                continue
            if not all(isinstance(r.get(p),dict) for p in ("player1","player2")):continue
            try:start=stamp(r["scheduled_at"])
            except (ValueError,KeyError,TypeError):continue
            if start.astimezone(TZ).date().isoformat()!=today or day(start)!=today:continue
            if not c.get("include_started",False) and start<=now:continue
            selector=str((r.get("betting") or {}).get("selection_id") or r.get("selection_id") or r.get("winner_id") or r.get("pick") or "")
            ident=(str(r["event_id"]),"aces" if k=="aces" else "match_winner",selector)
            if not selector or ident in seen:continue
            seen.add(ident);rows.append(r)
            # FREE pick can select among the whole confirmed TOP shortlist,
            # independently of the number of premium tips in the outbound message.
            if len(rows)>=max(c.get("max_per_section",7),10 if k=="top" else 0):
                break
        if rows:got[k]=rows
    return got

def messages(x,c,now,free_event_id=None):
    got=select_groups(x,c,now)
    if not got:return []
    today=day(now)
    date=now.astimezone(TZ).strftime("%d.%m.%Y")
    footer=str(c.get("footer") or FOOTER)
    def category_text(k,rows):
        names={"top":"🎾 TOP Picks | BlinQ","value":"💎 VALUE Picks | BlinQ","aces":"🎯 ESÁ | BlinQ"}
        return "\n".join([names[k],f"📅 {date}",""]+
                         [fmt(r,k,c,i,_name_map(rows)) for i,r in enumerate(rows,1)])
    outbound=[]
    premium=[]
    for k,rows in got.items():
        if (c.get("sections") or {}).get(k):
            premium.append(category_text(k,rows[:c.get("max_per_section",7)]))
    if premium:
        if c.get("layout","combined")=="separate":
            outbound.extend({"audience":"premium","text":"\n\n".join([HEADER,part,footer])} for part in premium)
        else:
            outbound.append({"audience":"premium","text":"\n\n".join([HEADER,*premium,footer])})
    if c.get("free_top_pick",True) and got.get("top"):
        # Stable deterministic pseudo-random selection by betting day.
        # A different action run on the same day cannot select another FREE pick.
        candidates=[row for row in got["top"] if str(row.get("event_id"))==str(free_event_id)] if free_event_id else got["top"]
        if not candidates: raise RuntimeError("Previously issued FREE TOP event is no longer in confirmed TOP; refusing changed FREE pick")
        winner=min(candidates,key=lambda r:hashlib.sha256(
            (today+"|"+str(r.get("event_id"))+"|"+str((r.get("betting") or {}).get("selection_id") or r.get("winner_id"))).encode("utf-8")).hexdigest())
        free="\n".join(["🎾 FREE | BlinQ",f"📅 {date}","",fmt(winner,"top",c,1).replace("1️⃣","🆓",1)])
        outbound.append({"audience":"free","text":"\n\n".join([HEADER,free,footer]),"free_event_id":str(winner.get("event_id"))})
    if any(len(item["text"])>4096 for item in outbound):
        raise RuntimeError("Telegram 4096 character limit; reduce max_per_section")
    return outbound

def prepare(a):
    now=stamp(a.now) if a.now else datetime.now(timezone.utc);v=config(a.config_url);key=due(v,now)
    if not key:print('{"status":"skipped","reason":"not_due"}');return
    old=load(a.state) if Path(a.state).is_file() else {"schema":1,"attempts":{}}
    attempts=old.get("attempts")
    if not isinstance(attempts,dict):raise RuntimeError("Invalid state")
    ident=day(now)+":"+key
    if ident in attempts:print('{"status":"skipped","reason":"already_reserved"}');return
    out=Path(a.output)
    sticky=old.get("free_picks") if isinstance(old.get("free_picks"),dict) else {}
    # A FREE selection is reserved before the Telegram call. Once reserved it
    # cannot be published twice, even by another manual or scheduled run.
    already_reserved_free=day(now) in sticky
    current_config={**v,"free_top_pick":False} if already_reserved_free else v
    msg=messages(snapshot(out/"assets"),current_config,now)
    if not msg:print('{"status":"skipped","reason":"no_eligible_rows"}');return
    save(out/"messages.json",msg)
    attempts[ident]={"reserved_at":now.isoformat(),"sha256":hashlib.sha256(json.dumps(msg,ensure_ascii=False).encode()).hexdigest()}
    for item in msg:
        if item.get("audience")=="free" and item.get("free_event_id"):
            sticky[day(now)]=item["free_event_id"]
    save(out/"state.json",{"schema":1,"attempts":dict(list(attempts.items())[-100:]),"free_picks":dict(list(sticky.items())[-30:])})
    (out/"ready").write_text(ident,encoding="utf-8")
    print(json.dumps({"status":"reserved","id":ident,"messages":len(msg)}))
def send(a):
    token=os.getenv("TGB");chat=os.getenv("TGCH")
    if not token or not chat:raise RuntimeError("Missing GH Secrets TGB or TGCH")
    if not (Path(a.output)/"ready").is_file():raise RuntimeError("Missing durable reservation")
    for item in load(Path(a.output)/"messages.json"):
        if not isinstance(item,dict) or item.get("audience") not in ("free","premium"): raise RuntimeError("Invalid reserved recipient")
        destination=(os.getenv("TGCH_FREE") or chat) if item["audience"]=="free" else chat
        req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",data=urllib.parse.urlencode({"chat_id":destination,"text":item["text"],"disable_web_page_preview":"true"}).encode(),method="POST")
        try:
            with urllib.request.urlopen(req,timeout=30) as f: answer=json.loads(f.read(16384))
        except Exception as exc:
            raise RuntimeError("Telegram request failed (credentials redacted): "+exc.__class__.__name__) from None
        if not answer.get("ok") or not (answer.get("result") or {}).get("message_id"):raise RuntimeError("Telegram send not confirmed")
        print("Telegram accepted message_id="+str(answer["result"]["message_id"]))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("action",choices=["prepare","send"])
    p.add_argument("--config-url",default="https://agreeable-sky-011a7fe10.7.azurestaticapps.net/api/v1/ui-config")
    p.add_argument("--state",default="ops/telegram-bot-state.json");p.add_argument("--output",default="/tmp/blinq-telegram");p.add_argument("--now",default="")
    a=p.parse_args();(prepare if a.action=="prepare" else send)(a)
