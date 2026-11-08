"""Morning Telegram must read the same current published generation as web."""
from datetime import datetime, timezone
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"scripts"))
import telegram_offer_publisher as tg

NOW = datetime(2026,11,7,5,30,tzinfo=timezone.utc)
GENERATED = "2026-11-07T05:25:00+00:00"
CONFIRMED_AT = "2026-11-07T05:29:00+00:00"

@pytest.fixture
def sources(monkeypatch):
    # These are already vetted by the existing signed private release reader.
    offer={"schema":1,"confirmed_only":True,"betting_day":"2026-11-07",
           "generated_at":CONFIRMED_AT,
           "source_feed_generated_at":GENERATED}
    web={"ok":True,"schema":1,"ready":True,"stale":False,
         "betting_day":"2026-11-07","generated_at":GENERATED,
         "visible_counts":{"top_daily_picks":3,"value_picks":1,
                           "ace_picks":9}}
    monkeypatch.setattr(tg,"select_groups",lambda *a,**kw:{
        "top":[{}, {}, {}], "value":[{}], "aces":[{} for _ in range(9)]
    })
    from tbt.services import issued_authority
    monkeypatch.setattr(issued_authority, "row_authority_key", lambda row, key: key + ":exact")
    web["offer_authority_keys"] = {k: [v + ":exact"] for k, v in tg.SECTIONS.items()}
    return offer,web

def test_early_send_allowed_for_current_verified_website_generation(sources):
    offer,site=sources
    assert tg.verified_website_morning_parity(offer,site,NOW)=={
        "betting_day":"2026-11-07","eligible":13,
        "website_generation_verified":True,
    }

@pytest.mark.parametrize("change",[
    {"stale":True},
    {"ready":False},
    {"generated_at":"2026-11-07T05:26:00+00:00"},
    {"betting_day":"2026-11-06"},
    {"schema":2},
    {"ok":False},
    {"visible_counts":{"top_daily_picks":3,"value_picks":1,"ace_picks":8}},
    {"visible_counts":{"top_daily_picks":3,"value_picks":1,"ace_picks":"9"}},
    {"visible_counts":{}},
])
def test_no_send_for_stale_partial_or_unverified_website(sources,change):
    offer,site=sources
    with pytest.raises(ValueError):
        tg.verified_website_morning_parity(offer,{**site,**change},NOW)

def test_no_send_if_source_feed_generation_missing_or_changed(sources):
    offer,site=sources
    for source in (None, "", "2026-11-07T05:26:00+00:00"):
        with pytest.raises(ValueError):
            tg.verified_website_morning_parity(
                {**offer, "source_feed_generated_at":source}, site, NOW)


def test_no_send_if_private_snapshot_is_wrong_day(sources):
    offer,site=sources
    with pytest.raises(ValueError):
        tg.verified_website_morning_parity({**offer,"betting_day":"2026-11-06"},site,NOW)


def test_same_generation_and_counts_do_not_authorize_different_picks(sources):
    offer, site = sources
    site["offer_authority_keys"]["top"] = ["another-contract"] * 3
    with pytest.raises(ValueError, match="exact issued"):
        tg.verified_website_morning_parity(offer, site, NOW)
