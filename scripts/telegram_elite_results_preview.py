"""One-off clearly labelled Telegram ELITE layout preview, never real settlements."""
from __future__ import annotations

import argparse
from pathlib import Path
import telegram_daily_results as results
import telegram_offer_publisher as tg

DAY="2026-10-31"
SELECTIONS=(
    ("top","Hanfmann",1.66,True),
    ("top","Virtanen",1.67,True),
    ("top","Gray",1.67,False),
    ("value","Hijikata",1.83,True),
    ("aces","Fritz",2.00,False),
    ("aces","Medvedev",2.00,True),
    ("aces","Zverev",2.00,False),
)


def preview():
    """Exercise the real report formatter with isolated synthetic test records."""
    frozen=[]
    verified=[]
    for index,(section,name,price,won) in enumerate(SELECTIONS,1):
        aces=section=="aces"
        row={
            "channel":section,
            "event_id":"SIMULATED-ELITE-"+str(index),
            "section":{"top":"top_daily","value":"value","aces":"ace"}[section],
            "market":"aces" if aces else "match_winner",
            "selection_id":"simulated-player-"+str(index),
            "scheduled_at":"2026-10-31T13:00:00+00:00",
            "name":name,
            "odds":price,
            "publication_key":"synthetic-market-line" if aces else "",
            "market_line":9.5 if aces else None,
            "projection_direction":"under" if aces else "",
        }
        frozen.append(row)
        verified.append({key:row[key] for key in (
            "event_id","section","market","selection_id","publication_key",
            "market_line","projection_direction",
        )} | {
            "odds":price,
            "price_status":"priced_projection",
            "result":{"correct":won,"void":False,"runtime_source":"match_status_snapshot"},
        })
    posts=results.combined_daily_report(frozen,verified,DAY,tg.branded_footer())
    if len(posts)!=1 or posts[0]["counts"]!={"won":4,"lost":3,"void":0,"pending":0}:
        raise RuntimeError("Unexpected synthetic preview outcome")
    message=posts[0]["text"]
    message=message.replace(
        tg.HEADER,
        tg.HEADER+"\n🧪 TEST – simulované výsledky, nie skutočné vyhodnotenie",
        1,
    )
    marker="\n\n"+tg.branded_footer()
    if marker not in message:
        raise RuntimeError("Missing clickable footer in synthetic preview")
    message=message.replace(
        marker,
        "\n\nLegenda: 🟪 VOID = zrušené/neplatné, ⏳ = čaká alebo odložené"+marker,
        1,
    )
    if len(message.encode("utf-16-le"))//2>4096:
        raise RuntimeError("Telegram test preview over limit")
    assert tg.telegram_link_entities(message)
    return message


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--output",default="/tmp/blinq-telegram")
    args=parser.parse_args()
    folder=Path(args.output)
    tg.save(folder/"messages.json",[{"audience":"elite","text":preview()}])
    folder.mkdir(parents=True,exist_ok=True)
    (folder/"ready").write_text("2026-10-31:elite-results-layout-v1",encoding="utf-8")
    print("Synthetic ELITE Telegram preview staged, no real settlements")


if __name__=="__main__":
    main()
