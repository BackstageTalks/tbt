"""Read-only evening pre-match market capture from publicly visible Fortuna SK pages.

This research source NEVER changes a model, issued pick, Telegram receipt or CDB.
It must not treat games or match winner as an ace quote, or infer missing lines.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime, time, timedelta, timezone
import hashlib
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import time as clock
import unicodedata
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ORIGIN = "https://www.ifortuna.sk"
INDEX = ORIGIN + "/stavkovanie/tenis?tab=matches"
TZ = ZoneInfo("Europe/Bratislava")
CARD = re.compile(r'<div\b[^>]*data-testing-selector="MatchDetailCard"[^>]*>', re.I)
OUTCOME = re.compile(r'\bdata-outcome="([^"]+)"')
DATE_TIME = re.compile(r'\b(\d{1,2})\.\s*(\d{1,2})\.\s*(\d{4})\s+(\d{1,2}):(\d{2})\b')
LINE = re.compile(r'^\s*([+-])\s*(\d{1,2}(?:[.,]\d+)?)\s*$')
START = re.compile(r'\bdata-testing-selector="PrematchStartDateTime"')
DETAIL = re.compile(r'\bdata-testing-selector="DetailPage"[^>]*\bdata-id="([^"]+)"')
PLAYER = re.compile(r'<span\b[^>]*class="[^"]*participants-panel__participant-label[^>]*>(.*?)</span>', re.S)


def norm(value):
    return ' '.join(''.join(c for c in unicodedata.normalize('NFKD', str(value or '').casefold())
                            if not unicodedata.combining(c)).split())


def attr(tag, key):
    found = re.search(r'\b' + re.escape(key) + r'="([^"]*)"', tag)
    return unescape(found.group(1)) if found else ''


class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        if tag != 'a':
            return
        href = dict(attrs).get('href') or ''
        full = urljoin(ORIGIN, href)
        p = urlsplit(full)
        if (p.scheme == 'https' and p.hostname == 'www.ifortuna.sk'
                and p.path.startswith('/stavkovanie/tenis/')
                and len(p.path.split('/')) >= 6):
            cleaned = ORIGIN + p.path.rstrip('/')
            if cleaned not in self.urls:
                self.urls.append(cleaned)


def parse_start(html):
    found = START.search(html)
    if not found:
        raise ValueError('no bookmaker PrematchStartDateTime')
    snippet = html[found.end():found.end() + 700]
    clean = re.sub(r'<[^>]+>', ' ', snippet)
    matched = DATE_TIME.search(unescape(clean))
    if not matched:
        raise ValueError('no full bookmaker local scheduled time')
    d, m, y, hh, mm = map(int, matched.groups())
    return datetime(y, m, d, hh, mm, tzinfo=TZ).astimezone(timezone.utc)


def market_kind(label):
    s = norm(unescape(label)).replace('&nbsp;', ' ')
    if not re.search(r'\b(es|esa|aces?)\b', s):
        return None
    if re.search(r'\b(set|sete|setu|tiebreak|tajbrejk)\b', s):
        return 'aces_set_other'
    if re.search(r'\b(viac|najviac|most|more|higher|winner)\b', s):
        return 'most_aces_match'
    if re.search(r'\b(pocet|total|over|under)\b', s):
        return 'player_aces_ou'
    return 'aces_unknown'


def _outcomes(fragment):
    rows = []
    for value in OUTCOME.findall(fragment):
        try:
            raw = json.loads(unescape(value))
            odds = float(raw.get('odds'))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if raw.get('displayType') != 'OPEN' or not 1.0 < odds <= 1000:
            continue
        rows.append({
            'selection': str(raw.get('longName') or '').strip(),
            'odds': odds,
            'market_id': str(raw.get('marketId') or ''),
            'option_id': str(raw.get('id') or ''),
        })
    return rows


def verified_pairs(kind, label, rows, players):
    """Only complete exact pairs, never two lines/books pooled together."""
    groups = {}
    for row in rows:
        groups.setdefault(row['market_id'], []).append(row)
    selected = []
    for market_id, options in groups.items():
        if not market_id or len(options) != 2 or not all(x['selection'] for x in options):
            continue
        if kind == 'player_aces_ou':
            # A player-specific total must name exactly one participant.
            named = [p for p in players if norm(p) in norm(label)]
            if len(named) != 1:
                continue
            parsed = [LINE.fullmatch(o['selection']) for o in options]
            if not all(parsed):
                continue
            parts = [(x.group(1), float(x.group(2).replace(',', '.'))) for x in parsed]
            if {p[0] for p in parts} != {'+', '-'} or parts[0][1] != parts[1][1]:
                continue
            line = parts[0][1]
            selected.append({'market_id': market_id, 'player': named[0], 'line': line,
                             'over': next(x['odds'] for x, p in zip(options, parts) if p[0] == '+'),
                             'under': next(x['odds'] for x, p in zip(options, parts) if p[0] == '-')})
        elif kind == 'most_aces_match':
            if {norm(o['selection']) for o in options} != {norm(p) for p in players}:
                continue
            selected.append({'market_id': market_id, 'two_way_outcomes': options,
                             'settlement': 'bookmaker_rules_not_yet_verified'})
    return selected


def parse_detail(html, url, captured_at):
    match = DETAIL.search(html)
    if not match:
        raise ValueError('no detail match id')
    players = [unescape(re.sub(r'<[^>]*>', '', x)).strip() for x in PLAYER.findall(html)[:2]]
    if len(players) != 2 or not all(players) or norm(players[0]) == norm(players[1]):
        raise ValueError('missing/ambiguous participants')
    start = parse_start(html)
    cards = list(CARD.finditer(html))
    relevant, markets_seen = [], len(cards)
    for i, item in enumerate(cards):
        label = attr(item.group(0), 'aria-label')
        kind = market_kind(label)
        if kind is None:
            continue
        content = html[item.end(): cards[i+1].start() if i + 1 < len(cards) else len(html)]
        rows = _outcomes(content)
        relevant.append({'market_name': label, 'kind': kind, 'outcomes_observed': len(rows),
                         'verified_pairs': verified_pairs(kind, label, rows, players)})
    return {
        'provider': 'fortuna_sk', 'event_id': match.group(1), 'players': players,
        'scheduled_at': start.isoformat(), 'captured_at': captured_at.isoformat(),
        'source_url': url, 'source_sha256': hashlib.sha256(html.encode()).hexdigest(),
        'market_groups_seen': markets_seen, 'aces_markets': relevant,
    }


def fetch(url):
    p = urlsplit(url)
    if p.scheme != 'https' or p.hostname != 'www.ifortuna.sk':
        raise ValueError('Source host not permitted')
    request = Request(url, headers={'User-Agent': 'BlinQ-Research-Prematch-Audit/1.0', 'Accept': 'text/html'})
    with urlopen(request, timeout=22) as response:
        if response.status != 200:
            raise RuntimeError('bookmaker HTTP non-200')
        content = response.read(5_000_001)
    if len(content) > 5_000_000:
        raise RuntimeError('oversized response')
    html = content.decode('utf-8', errors='replace')
    if 'V aplikácii nastala neočakávaná chyba' in html or 'V aplikaci nastala neočekávaná chyba' in html:
        raise RuntimeError('bookmaker application error')
    return html


def collect(target_day, *, max_events=20, sleep_seconds=0.8, now=None, get=fetch):
    now = now or datetime.now(timezone.utc)
    start = datetime.combine(target_day, time(6), TZ).astimezone(timezone.utc)
    end = datetime.combine(target_day + timedelta(days=1), time(6), TZ).astimezone(timezone.utc)
    if now >= start:
        raise ValueError('evening capture must occur before next betting day')
    directory = Links()
    directory.feed(get(INDEX))
    urls = directory.urls[:max_events]
    report = {'schema': 1, 'status': 'audited', 'source': 'public_fortuna_sk',
              'mode': 'read_only_evening_aces', 'target_betting_day': target_day.isoformat(),
              'captured_at': now.isoformat(), 'target_start': start.isoformat(),
              'target_end': end.isoformat(), 'candidate_urls': len(directory.urls),
              'probed_urls': len(urls), 'events_in_target_window': [], 'errors': [],
              'cdb_writes': 0, 'published_picks_changed': 0, 'provider_paid_calls': 0}
    for idx, url in enumerate(urls):
        if idx and sleep_seconds:
            clock.sleep(sleep_seconds)
        try:
            parsed = parse_detail(get(url), url, datetime.now(timezone.utc))
            event_start = datetime.fromisoformat(parsed['scheduled_at'])
            if start <= event_start < end:
                report['events_in_target_window'].append(parsed)
        except (OSError, ValueError, RuntimeError) as exc:
            report['errors'].append({'url': url, 'error': exc.__class__.__name__})
    report['exact_aces_pairs'] = sum(len(m['verified_pairs']) for e in report['events_in_target_window']
                                     for m in e['aces_markets'])
    report['aces_market_groups'] = sum(len(e['aces_markets']) for e in report['events_in_target_window'])
    if not urls or (urls and len(report['errors']) == len(urls)):
        report['status'] = 'source_unavailable'
    elif report['exact_aces_pairs'] == 0:
        report['status'] = 'no_exact_aces_market_available'
    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--target-day', type=date.fromisoformat,
                        default=(datetime.now(TZ) + timedelta(days=1)).date())
    parser.add_argument('--max-events', type=int, default=20)
    parser.add_argument('--out', default='reports/skcz-evening/fortuna.json')
    args = parser.parse_args()
    if not 1 <= args.max_events <= 60:
        parser.error('max-events must be 1..60')
    report = collect(args.target_day, max_events=args.max_events)
    dest = Path(args.out)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + '\n')
    print(json.dumps({k: report[k] for k in ('status', 'target_betting_day', 'probed_urls',
               'exact_aces_pairs', 'aces_market_groups', 'cdb_writes')}, sort_keys=True))
    if report['status'] == 'source_unavailable':
        raise SystemExit(2)


if __name__ == '__main__':
    main()
