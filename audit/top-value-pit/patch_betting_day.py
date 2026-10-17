"""Apply the 06:00 Bratislava betting-day research contract to the pinned audit scripts.

Research-only patch; never modifies production modules.
"""
from pathlib import Path

p = Path("scripts/backtest_top_value_pit.py")
s = p.read_text()
assert "CUTOFF_HOUR = 12" in s, "unexpected pinned source"
s = s.replace("CUTOFF_HOUR = 12", "BETTING_DAY_START_HOUR = 6")
s = s.replace(
    "return (x.astimezone(TZ)-timedelta(hours=6)).date().isoformat()",
    "local=x.astimezone(TZ)\n    d=local.date()-timedelta(days=1) if local.hour < BETTING_DAY_START_HOUR else local.date()\n    return d.isoformat()")
s = s.replace("time(CUTOFF_HOUR)", "time(BETTING_DAY_START_HOUR)")
before = """def is_at_cutoff(r):
    t=cutoff(r['betting_day'])
    issued=dt(r['issued_at']); scheduled=dt(r['scheduled_at']); quote=dt(r.get('quote_captured_at'))
    return bool(issued and scheduled and issued<=t<scheduled and quote and quote<=issued and r['snapshot_verified'])
"""
after = """def is_at_cutoff(r):
    \"\"\"Coverage of a real published event during a 06:00-06:00 betting day.

    This is NOT a simultaneous daily candidate replay. Published-only
    probability ranking is a descriptive/oracle-style comparison.
    \"\"\"
    start=cutoff(r['betting_day'])
    next_day=(datetime.fromisoformat(r['betting_day'])+timedelta(days=1)).date().isoformat()
    end=cutoff(next_day)
    issued=dt(r['issued_at']); scheduled=dt(r['scheduled_at']); quote=dt(r.get('quote_captured_at'))
    return bool(issued and scheduled and start<=issued<end and issued<scheduled
                and quote and quote<=issued and r['snapshot_verified'])
"""
assert before in s, "expected published-clock contract not found"
s=s.replace(before, after)
assert "'cutoff_local':'12:00 Europe/Bratislava'" in s
s=s.replace("'cutoff_local':'12:00 Europe/Bratislava'",
"""'betting_day_local':'06:00-06:00 Europe/Bratislava',
            'decision_clock':'immutable publication time; published-only ranking descriptive, not PIT candidate replay'""")
s=s.replace("'at_cutoff_strict_pool':", "'verified_published_during_betting_day':")
p.write_text(s)

p = Path("scripts/backtest_archived_candidates.py")
s=p.read_text()
assert "if generated<=cutoff(d):buckets[d].append((generated,snapshot))" in s
s=s.replace("from backtest_top_value_pit import dt, num, prob, load, cutoff, summarize",
            "from backtest_top_value_pit import dt, num, prob, load, cutoff, day, summarize")
before="""        # The scheduled betting day is the calendar day of the pre-match snapshot
        # in Bratislava; only the latest observable snapshot before noon is used.
        from zoneinfo import ZoneInfo
        d=generated.astimezone(ZoneInfo('Europe/Bratislava')).date().isoformat()
        if generated<=cutoff(d):buckets[d].append((generated,snapshot))"""
after="""        # Choose the last genuinely captured snapshot during local 06:00-06:00
        # betting day. Candidate fields must predate this exact snapshot.
        d=day(generated)
        buckets[d].append((generated,snapshot))"""
assert before in s
s=s.replace(before,after)
before="""            if not event or not target or not when or when<=cutoff(d):
                diag['invalid_or_started_before_cutoff']+=1;continue"""
after="""            if not event or not target or not when or when<=at:
                diag['invalid_or_started_before_snapshot']+=1;continue"""
assert before in s
s=s.replace(before,after)
s=s.replace("'later_is_pristine':False,'production_changed':False}",
"""'later_is_pristine':False,'production_changed':False,
            'betting_day_local':'06:00-06:00 Europe/Bratislava',
            'decision_clock':'last genuine archived snapshot during each betting day'}""")
p.write_text(s)
print("BETTING_DAY_PATCH_APPLIED: Europe/Bratislava 06:00 -> next 06:00")
