"""Read confirmed BlinQ offer and publish through Telegram without paid APIs."""
import argparse, hashlib, json, math, os, re, subprocess, sys, urllib.parse, urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "api"))
from tbt.services.entitlements import _daily_rows
TZ=ZoneInfo("Europe/Bratislava")
SECTIONS={"top":"top_daily_picks","value":"value_picks","aces":"ace_picks"}
LABELS={"top":"🏆 TOP","value":"💎 VALUE","aces":"🎯 ACES"}
# Native Telegram FREE button (🆓) has no TOP/VALUE/ACES Unicode equivalents.
# Keep compact, client-independent ASCII labels instead of simulated custom emoji.
OFFER_ICONS={"top":"🅃","value":"🅅","aces":"🄰"}
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
    if type(v.get("max_per_section",0)) is not int or not 0<=v.get("max_per_section",0)<=1000: raise ValueError("Invalid limit")
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
HEADER="🎾 BlinQ | Tennis Intelligence"
FOOTER="ℹ️ Analytical preview"
BRAND_LINK_TEXT="BlinQ Stat Engine"
BRAND_FOOTER="by " + BRAND_LINK_TEXT
BRAND_URL="https://agreeable-sky-011a7fe10.7.azurestaticapps.net/follow-the-data/"


def branded_footer(value=None):
    """Compact one-line standard footer; preserve other Admin disclaimers."""
    text=str(value or FOOTER).strip()
    for old in ("🧠 by BackstageTalks Data Engine", "by BackstageTalks Data Engine",
                BRAND_FOOTER):
        text=text.replace(old,"").strip()
    if text in ("ℹ️ Analytical preview only","ℹ️ Analytical preview"):
        return FOOTER+" "+BRAND_FOOTER
    return (text+"\n" if text else "")+BRAND_FOOTER


def telegram_link_entities(message):
    """Offsets are Telegram UTF-16 code units, not Python codepoints.

    Text entities are safer than interpolating player names into HTML parse mode.
    """
    pos=message.rfind(BRAND_FOOTER)
    if pos<0:
        return []
    start=pos+len("by ")
    return [{"type":"text_link",
             "offset":len(message[:start].encode("utf-16-le"))//2,
             "length":len(BRAND_LINK_TEXT.encode("utf-16-le"))//2,
             "url":BRAND_URL}]

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

def fmt(r,k,c,index=1,name_map=None,prefix_override=None):
    bet=r.get("betting") or {}
    selected=_selection_name(r)
    name=(name_map or {}).get(selected) or selected.split()[-1] if selected else "—"
    time=stamp(r["scheduled_at"]).astimezone(TZ).strftime("%H:%M")
    if k=="aces":
        contract=str(r.get("price_contract") or "").lower()
        if contract=="player_total_ou":
            side=str(r.get("ou_side") or "").lower()
            market_line=num(r.get("market_line"))
            if side not in ("over","under") or market_line is None or market_line<0:
                raise ValueError("Incomplete confirmed ACES over/under contract")
            values=[f"{side.title()} {market_line:.1f} es"]
            # O/U probability and Most Aces confidence describe different outcomes.
            confidence=num(r.get("model_probability"))
        else:
            # The model predicts which player will hit the most aces;
            # its numeric count projection is not a bookmaker line.
            values=["najviac es"]
            confidence=num(r.get("projection_confidence"))
        if confidence is not None:
            values.append(f"{(confidence*100 if abs(confidence)<=1 else confidence):.1f}%")
        # This is the selected player's expected ace count, not the bookmaker
        # O/U line and not the combined projection for both competitors.
        projection=num(r.get("projection"))
        if projection is not None and math.isfinite(projection) and projection>=0:
            values.append(f"proj. {projection:.1f} es")
    else:
        prob=num(bet.get("blinq_probability") or bet.get("model_probability") or r.get("blinq_probability") or r.get("probability"))
        values=[f"{(prob*100 if abs(prob)<=1 else prob):.1f}%" if prob is not None else "—"] if c.get("show_probability",True) else []
    odds=num(bet.get("odds") or r.get("odds"))
    if c.get("show_odds",True):
        values.append(f"{odds:.2f}" if odds is not None and odds>1 else "—")
    prefix=prefix_override or OFFER_ICONS[k]
    line=f"{prefix} | {name} | {time} | "+" | ".join(values)
    if k=="aces" and len(line)>44 and confidence is not None:
        # Keep the exact prediction and genuine odds readable on narrow phones.
        values=[item for item in values if item!=f"{(confidence*100 if abs(confidence)<=1 else confidence):.1f}%"]
        line=f"{prefix} | {name} | {time} | "+" | ".join(values)
    return line

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
            limit=c.get("max_per_section",0)
            if limit and len(rows)>=max(limit,10 if k=="top" else 0):
                break
        if rows:got[k]=rows
    return got

def messages(x,c,now,free_event_id=None):
    got=select_groups(x,c,now)
    if not got:return []
    today=day(now)
    date=now.astimezone(TZ).strftime("%d.%m.%Y")
    footer=branded_footer(c.get("footer"))
    outbound=[]
    # User-facing order: TOP -> Value -> Aces, without category headings.
    # 0 means ALL issued/eligible picks; never silently truncate the offer.
    # Telegram's 4096 character cap is handled by splitting the message.
    limit=c.get("max_per_section",0)
    premium_groups=[(key,rows[:limit] if limit else rows) for key,rows in got.items()
                    if (c.get("sections") or {}).get(key)]
    shown=[row for _,rows in premium_groups for row in rows]
    names=_name_map(shown)
    def lines(records):
        return "\n".join(fmt(row,key,c,i,names) for i,(key,row) in enumerate(records,1))
    def split_long_message(records):
        # If the complete published offer will not fit one Telegram message,
        # split at row boundaries; preserve original order and global numbering.
        base=[HEADER,f"📅 {date}"]
        chunks=[]
        current=[]
        for index,(key,row) in enumerate(records,1):
            line=fmt(row,key,c,index,names)
            candidate="\n\n".join(base+["\n".join(current+[line]),footer])
            if len(candidate.encode("utf-16-le"))//2>4096:
                if not current:
                    raise RuntimeError("A Telegram prediction row exceeds safe size")
                chunks.append("\n\n".join(base+["\n".join(current),footer]))
                current=[line]
                if len("\n\n".join(base+[line,footer]).encode("utf-16-le"))//2>4096:
                    raise RuntimeError("A Telegram prediction row exceeds safe size")
            else:
                current.append(line)
        if current:
            chunks.append("\n\n".join(base+["\n".join(current),footer]))
        return chunks

    if premium_groups:
        if c.get("layout","combined")=="separate":
            for key,rows in premium_groups:
                outbound.extend({"audience":"premium","text":message}
                                for message in split_long_message([(key,row) for row in rows]))
        else:
            records=[(key,row) for key,rows in premium_groups for row in rows]
            outbound.extend({"audience":"premium","text":message}
                            for message in split_long_message(records))
    if c.get("free_top_pick",True) and got.get("top"):
        # Stable deterministic pseudo-random selection by betting day.
        # A different action run on the same day cannot select another FREE pick.
        candidates=[row for row in got["top"] if str(row.get("event_id"))==str(free_event_id)] if free_event_id else got["top"]
        if not candidates: raise RuntimeError("Previously issued FREE TOP event is no longer in confirmed TOP; refusing changed FREE pick")
        winner=min(candidates,key=lambda r:hashlib.sha256(
            (today+"|"+str(r.get("event_id"))+"|"+str((r.get("betting") or {}).get("selection_id") or r.get("winner_id"))).encode("utf-8")).hexdigest())
        free="\n".join(["🎾 FREE | BlinQ",f"📅 {date}","",fmt(winner,"top",c,1,prefix_override="🆓 FREE")])
        outbound.append({"audience":"free","text":"\n\n".join([HEADER,free,footer]),"free_event_id":str(winner.get("event_id"))})
    if any(len(item["text"].encode("utf-16-le"))//2>4096 for item in outbound):
        raise RuntimeError("Telegram 4096 character limit; reduce max_per_section")
    return outbound


def result_reference(row,section):
    """Immutable compact reference to a sendable and subsequently gradable pick."""
    betting=row.get("betting") or {}
    real_section={"top":"top_daily","value":"value","aces":"ace","free":"top_daily"}[section]
    market="aces" if section=="aces" else "match_winner"
    selection=str(betting.get("selection_id") or row.get("selection_id") or row.get("winner_id") or "")
    pubs=[p for p in row.get("market_publications") or [] if isinstance(p,dict)
          and p.get("section")==real_section and str(p.get("market") or market)==market
          and str(p.get("selection_id") or p.get("winner_id") or "")==selection]
    pub=pubs[0] if len(pubs)==1 else {}
    odds=num(pub.get("odds") or betting.get("odds") or row.get("odds"))
    if section=="aces" and pub and pub.get("price_status")!="priced_projection":odds=None
    return {"event_id":str(row["event_id"]), "section":real_section,
            "channel":section, "market":market, "selection_id":selection,
            "publication_key":str(pub.get("publication_key") or ""),
            "market_line":pub.get("market_line"),
            "projection_direction":str(pub.get("ou_side") or pub.get("projection_direction") or ""),
            "scheduled_at":str(row["scheduled_at"]),
            "name":_selection_name(row), "odds":odds if odds and odds>1 else None,
            "projection":num(row.get("projection")) if market=="aces" else None}

def _same_frozen_selection(current, frozen):
    """No change to exact sent identity, price or O/U settlement contract."""
    for key in ("event_id","section","channel","market","selection_id",
                "publication_key","market_line","projection_direction"):
        if str(current.get(key) or "")!=str(frozen.get(key) or ""):
            return False
    old_price=num(frozen.get("odds"));new_price=num(current.get("odds"))
    return (old_price is None and new_price is None) or (
        old_price is not None and new_price is not None
        and abs(old_price-new_price)<0.00001)

def _original_offer_only(confirmed, sent, now):
    """Make a reformat of the previously issued offer, never new model picks."""
    source=select_groups(confirmed,{"sections":{k:True for k in SECTIONS},
        "free_top_pick":True,"include_started":True,"max_per_section":0},now)
    selected={key:[] for key in SECTIONS}
    used=set()
    for frozen in sent.get("rows") or []:
        section=frozen.get("channel")
        if section=="free":
            continue
        if section not in SECTIONS:
            raise RuntimeError("Unexpected original Telegram section")
        matches=[row for row in source.get(section,[])
                 if _same_frozen_selection(result_reference(row,section),frozen)]
        if len(matches)!=1:
            raise RuntimeError("Original issued Telegram pick no longer matches a unique confirmed snapshot row")
        identity=(section,str(frozen["event_id"]),str(frozen["selection_id"]))
        if identity in used:
            raise RuntimeError("Duplicated frozen original identity")
        used.add(identity)
        selected[section].append(matches[0])
    if len(used)!=len([row for row in sent.get("rows") or [] if row.get("channel")!="free"]):
        raise RuntimeError("Frozen publication count mismatch")
    # Keep the original TOP set through the shared public selection helper.
    frozen_offer={**confirmed,"top_daily_picks":selected["top"],
                  "value_picks":selected["value"],"ace_picks":selected["aces"]}
    if _daily_rows(frozen_offer)!=selected["top"]:
        raise RuntimeError("Frozen original TOP no longer passes exact public TOP selection")
    return frozen_offer


def mark_sent(args):
    """Called only after all message IDs were received; commit separate state read-back."""
    out=Path(args.output)
    ident=(out/"ready").read_text(encoding="utf-8").strip()
    state=load(out/"state.json")
    attempt=(state.get("attempts") or {}).get(ident) or (state.get("reposts") or {}).get(ident)
    receipt=load(out/"receipt.json")
    if not attempt or not isinstance(receipt,list):
        raise RuntimeError("Missing confirmed Telegram receipt")
    expected=load(out/"messages.json")
    if len(receipt)!=len(expected) or not all(isinstance(n,int) and n>0 for n in receipt):
        raise RuntimeError("Incomplete Telegram send receipt")
    attempt["status"]="sent"
    attempt["sent_at"]=datetime.now(timezone.utc).isoformat()
    attempt["message_ids"]=receipt
    save(out/"state.json",state)
    print(json.dumps({"status":"sent","id":ident,"confirmed":len(receipt)}))

def _daily_id(now):
    return day(now)+":daily:0620"

def queue_daily(a):
    """Durable, data-free send intent. Commit this ledger before waiting for data."""
    now=stamp(a.now) if a.now else datetime.now(timezone.utc)
    ident=_daily_id(now)
    state=load(a.state) if Path(a.state).is_file() else {"schema":1,"attempts":{}}
    attempts=state.setdefault("attempts",{})
    if not isinstance(attempts,dict):raise RuntimeError("Invalid state")
    # Never schedule another premium batch for a day already reserved or sent.
    if any(key.startswith(day(now)+":") and isinstance(value,dict)
           and value.get("status") in ("reserved","sent")
           for key,value in attempts.items()):
        print(json.dumps({"status":"skipped","reason":"already_reserved_or_sent","id":ident}))
        return
    if ident not in attempts:
        attempts[ident]={"status":"queued","queued_at":now.isoformat()}
        save(a.state,state)
    print(json.dumps({"status":"queued","id":ident}))

def prepare(a):
    now=stamp(a.now) if a.now else datetime.now(timezone.utc);v=config(a.config_url)
    repost=getattr(a,"preview_format",False)
    if getattr(a,"daily",False) or repost:
        # Explicit operator-approved issue; no mutation to Admin configuration.
        v={**v,"enabled":True,"sections":{k:True for k in SECTIONS},
           "layout":"combined","max_per_section":0,"free_top_pick":True}
        if repost:
            v["include_started"]=True  # Editing the exact morning offer, not new picks
        revision=getattr(a,"preview_revision","format-v2-no-ev")
        if not re.fullmatch(r"[A-Za-z0-9-]{8,48}",revision):
            raise ValueError("Invalid explicit preview revision")
        key="repost:"+revision if repost else "daily:0620"
    else:
        key=due(v,now)
    if not key:print('{"status":"skipped","reason":"not_due"}');return
    old=load(a.state) if Path(a.state).is_file() else {"schema":1,"attempts":{}}
    attempts=old.get("attempts")
    if not isinstance(attempts,dict):raise RuntimeError("Invalid state")
    ident=day(now)+":"+key
    reposts=old.get("reposts") or {}
    if not isinstance(reposts,dict):raise RuntimeError("Invalid repost ledger")
    if repost and ident in reposts:
        print('{"status":"skipped","reason":"repost_already_reserved_or_sent"}');return
    # A legacy Admin schedule, a manual request and the 06:20 daily job must
    # never independently publish the same betting day's offer.
    # Explicit, separately tracked operator-approved format reposts are exempt.
    if not repost and any(k!=ident and k.startswith(day(now)+":")
                       and isinstance(val,dict) and val.get("status") in ("reserved","sent")
                       for k,val in attempts.items()):
        print('{"status":"skipped","reason":"daily_offer_already_reserved"}');return
    if not repost and ident in attempts and attempts[ident].get("status")!="queued":
        print('{"status":"skipped","reason":"already_reserved"}');return
    previous=attempts.get(_daily_id(now)) if repost else None
    if repost and (not isinstance(previous,dict) or previous.get("status")!="sent"
                   or not previous.get("message_ids") or not previous.get("rows")):
        raise RuntimeError("No previously confirmed same-day Telegram delivery to reformat")
    out=Path(a.output)
    sticky=old.get("free_picks") if isinstance(old.get("free_picks"),dict) else {}
    confirmed=snapshot(out/"assets")
    if repost:confirmed=_original_offer_only(confirmed,previous,now)
    msg=messages(confirmed,v,now,free_event_id=sticky.get(day(now)))
    if not msg:print('{"status":"skipped","reason":"no_eligible_rows"}');return
    if repost and len(msg)!=len(previous["message_ids"]):
        raise RuntimeError("Reformatted message count does not match original receipts")
    groups=select_groups(confirmed,v,now)
    sent_rows=[]
    for section,rows in groups.items():
        if not (v.get("sections") or {}).get(section):
            continue
        limit=v.get("max_per_section",0)
        for row in (rows[:limit] if limit else rows):
            sent_rows.append(result_reference(row,section))
    free=next((item for item in msg if item.get("audience")=="free"),None)
    if free:
        top=next((row for row in groups.get("top",[]) if str(row.get("event_id"))==free["free_event_id"]),None)
        if top is None:raise RuntimeError("FREE pick missing from confirmed TOP")
        sent_rows.append(result_reference(top,"free"))
    if not sent_rows:raise RuntimeError("No exact Telegram rows to evaluate")
    if repost:
        original=previous["rows"]
        if len(sent_rows)!=len(original) or any(
                not _same_frozen_selection(now_row,old_row)
                for now_row,old_row in zip(sent_rows,original)):
            raise RuntimeError("Preview would change previously published picks")
    save(out/"messages.json",msg)
    slot=reposts if repost else attempts
    slot[ident]={"reserved_at":now.isoformat(),"status":"reserved",
                 "rows":sent_rows if not repost else [],
                 "sha256":hashlib.sha256(json.dumps(msg,ensure_ascii=False).encode()).hexdigest()}
    for item in msg:
        if item.get("audience")=="free" and item.get("free_event_id"):
            sticky[day(now)]=item["free_event_id"]
    save(out/"state.json",{**old,"schema":1,
        "attempts":dict(list(attempts.items())[-100:]),
        "reposts":dict(list(reposts.items())[-30:]),
        "free_picks":dict(list(sticky.items())[-30:])})
    (out/"ready").write_text(ident,encoding="utf-8")
    print(json.dumps({"status":"reserved","id":ident,"messages":len(msg)}))
def send(a):
    token=os.getenv("TGB");chat=os.getenv("TGCH")
    if not token or not chat:raise RuntimeError("Missing GH Secrets TGB or TGCH")
    if not (Path(a.output)/"ready").is_file():raise RuntimeError("Missing durable reservation")
    receipts=[]
    for item in load(Path(a.output)/"messages.json"):
        if not isinstance(item,dict) or item.get("audience") not in ("free","premium","elite"): raise RuntimeError("Invalid reserved recipient")
        destination=chat
        # Telegram text_link entities keep the visible footer compact and
        # clickable without untrusted player text passing through HTML parsing.
        body={"chat_id":destination,"text":item["text"],"disable_web_page_preview":"true"}
        entities=telegram_link_entities(item["text"])
        if entities:
            body["entities"]=json.dumps(entities,ensure_ascii=False)
        req=urllib.request.Request("https://api.telegram.org/bot"+token+"/sendMessage",data=urllib.parse.urlencode(body).encode(),method="POST")
        try:
            with urllib.request.urlopen(req,timeout=30) as f: answer=json.loads(f.read(16384))
        except Exception as exc:
            raise RuntimeError("Telegram request failed (credentials redacted): "+exc.__class__.__name__) from None
        if not answer.get("ok") or not (answer.get("result") or {}).get("message_id"):raise RuntimeError("Telegram send not confirmed")
        message_id=int(answer["result"]["message_id"])
        receipts.append(message_id)
        save(Path(a.output)/"receipt.json",receipts)
        print("Telegram accepted message_id="+str(message_id))
if __name__=="__main__":
    p=argparse.ArgumentParser();p.add_argument("action",choices=["prepare","queue-daily","send","mark-sent"])
    p.add_argument("--config-url",default="https://agreeable-sky-011a7fe10.7.azurestaticapps.net/api/v1/ui-config")
    p.add_argument("--state",default="ops/telegram-bot-state.json");p.add_argument("--output",default="/tmp/blinq-telegram");p.add_argument("--now",default="")
    p.add_argument("--daily",action="store_true",help="Operator-approved full daily offer")
    p.add_argument("--preview-format",action="store_true",help="One-time repost of exact sent offer with updated presentation")
    p.add_argument("--preview-revision",default="format-v2-no-ev",help="Stable unique operator-approved repost revision")
    a=p.parse_args();{"prepare":prepare,"queue-daily":queue_daily,"send":send,"mark-sent":mark_sent}[a.action](a)
