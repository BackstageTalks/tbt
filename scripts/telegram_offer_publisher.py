"""Read confirmed BlinQ offer and publish through Telegram without paid APIs."""
import argparse, hashlib, json, os, re, subprocess, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
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
    for f in ("enabled","include_started","show_probability","show_odds"):
        if type(v.get(f,False)) is not bool: raise ValueError("Invalid "+f)
    if type(s.get("enabled",False)) is not bool: raise ValueError("Invalid schedule enabled")
    return v
def due(v,now):
    if not v.get("enabled") or not any((v.get("sections") or {}).get(k) for k in SECTIONS): return None
    r=v.get("manual_request") or {}
    if isinstance(r,dict) and re.fullmatch("[A-Za-z0-9_-]{8,80}",str(r.get("id",""))):
        age=(now-stamp(r.get("created_at"))).total_seconds()
        if 0<=age<=1800 and day(stamp(r["created_at"]))==day(now): return "manual:"+r["id"]
    s=v.get("schedule") or {};local=now.astimezone(TZ)
    if not s.get("enabled") or local.weekday() not in s.get("weekdays",list(range(7))): return None
    h,m=map(int,s.get("time","08:15").split(":"));planned=local.replace(hour=h,minute=m,second=0,microsecond=0)
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
def fmt(r,k,c):
    a,b=(r.get(n) or {} for n in ("player1","player2")); bet=r.get("betting") or {}
    sid=str(bet.get("selection_id") or r.get("selection_id") or r.get("winner_id") or "")
    p=next((x.get("name") for x in (a,b) if str(x.get("id"))==sid),None) or r.get("pick") or r.get("selection") or sid
    time=stamp(r["scheduled_at"]).astimezone(TZ).strftime("%H:%M")
    parts=[]
    if k=="aces":
        if num(r.get("projection")) is not None: parts.append("esá %.1f"%num(r["projection"]))
        if num(r.get("opponent_projection")) is not None: parts.append("súper %.1f"%num(r["opponent_projection"]))
        if num(r.get("projection_confidence")) is not None: parts.append("confidence %.1f%%"%(num(r["projection_confidence"])*100))
    else:
        prob=num(bet.get("blinq_probability") or bet.get("model_probability") or r.get("blinq_probability") or r.get("probability"))
        if c.get("show_probability",True) and prob is not None: parts.append("P %.1f%%"%(prob*100))
    odds=num(bet.get("odds") or r.get("odds"))
    if c.get("show_odds",True):
        if odds and odds>1: parts.append("kurz %.2f"%odds)
        elif k=="aces": parts.append("bez potvrdeného kurzu")
    if k=="value":
        ev=num(bet.get("expected_value") if "expected_value" in bet else r.get("expected_value"))
        if ev is not None: parts.append("EV %+.1f%%"%(ev*100))
    return "🎾 %s – %s\n⏰ %s · %s\n%s"%(a.get("name","—"),b.get("name","—"),time,p," · ".join(parts))
def messages(x,c,now):
    today=day(now)
    if x.get("betting_day")!=today or day(stamp(x["generated_at"]))!=today or stamp(x["generated_at"])>now+timedelta(minutes=5): raise RuntimeError("Wrong betting day")
    got={};seen=set()
    for k,key in SECTIONS.items():
        if not (c.get("sections") or {}).get(k): continue
        rows=[]
        for r in x.get(key) or []:
            if not isinstance(r,dict) or not r.get("event_id") or (k=="aces" and r.get("market")!="aces"): continue
            try: start=stamp(r["scheduled_at"])
            except (ValueError,KeyError,TypeError): continue
            if start.astimezone(TZ).date().isoformat()!=today or day(start)!=today or (not c.get("include_started",False) and start<=now):continue
            if not all(isinstance(r.get(p),dict) for p in ("player1","player2")):continue
            sel=str((r.get("betting") or {}).get("selection_id") or r.get("selection_id") or r.get("winner_id") or r.get("pick") or "")
            identity=(r["event_id"],"aces" if k=="aces" else "match_winner",sel)
            if not sel or identity in seen:continue
            seen.add(identity);rows.append(r)
            if len(rows)>=c.get("max_per_section",7): break
        if rows:got[k]=rows
    if not got:return []
    title="🎾 BlinQ · "+now.astimezone(TZ).strftime("%d.%m.%Y")
    footer=str(c.get("footer","BlinQ · Tennis Intelligence"))
    if c.get("layout")=="separate":
        result=["\n\n".join([title,LABELS[k],*(fmt(r,k,c) for r in rows),footer]) for k,rows in got.items()]
    else:
        parts=[title]
        for k,rows in got.items():parts.extend([LABELS[k],*(fmt(r,k,c) for r in rows)])
        result=["\n\n".join([*parts,footer])]
    if any(len(t)>4096 for t in result): raise RuntimeError("Telegram 4096 character limit; lower count")
    return result
def prepare(a):
    now=stamp(a.now) if a.now else datetime.now(timezone.utc);v=config(a.config_url);key=due(v,now)
    if not key:print('{"status":"skipped","reason":"not_due"}');return
    old=load(a.state) if Path(a.state).is_file() else {"schema":1,"attempts":{}}
    attempts=old.get("attempts")
    if not isinstance(attempts,dict):raise RuntimeError("Invalid state")
    ident=day(now)+":"+key
    if ident in attempts:print('{"status":"skipped","reason":"already_reserved"}');return
    out=Path(a.output);msg=messages(snapshot(out/"assets"),v,now)
    if not msg:print('{"status":"skipped","reason":"no_eligible_rows"}');return
    save(out/"messages.json",msg)
    attempts[ident]={"reserved_at":now.isoformat(),"sha256":hashlib.sha256(json.dumps(msg,ensure_ascii=False).encode()).hexdigest()}
    save(out/"state.json",{"schema":1,"attempts":dict(list(attempts.items())[-100:])})
    (out/"ready").write_text(ident,encoding="utf-8")
    print(json.dumps({"status":"reserved","id":ident,"messages":len(msg)}))
def send(a):
    token=os.getenv("TGB");chat=os.getenv("TGCH")
    if not token or not chat:raise RuntimeError("Missing GH Secrets TGB or TGCH")
    if not (Path(a.output)/"ready").is_file():raise RuntimeError("Missing durable reservation")
    for msg in load(Path(a.output)/"messages.json"):
        req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",data=urllib.parse.urlencode({"chat_id":chat,"text":msg,"disable_web_page_preview":"true"}).encode(),method="POST")
        with urllib.request.urlopen(req,timeout=30) as f: answer=json.loads(f.read(16384))
        if not answer.get("ok") or not (answer.get("result") or {}).get("message_id"):raise RuntimeError("Telegram send not confirmed")
        print("Telegram accepted message_id="+str(answer["result"]["message_id"]))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("action",choices=["prepare","send"])
    p.add_argument("--config-url",default="https://agreeable-sky-011a7fe10.7.azurestaticapps.net/api/v1/ui-config")
    p.add_argument("--state",default="ops/telegram-bot-state.json");p.add_argument("--output",default="/tmp/blinq-telegram");p.add_argument("--now",default="")
    a=p.parse_args();(prepare if a.action=="prepare" else send)(a)
