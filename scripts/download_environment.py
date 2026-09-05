"""Archive city/day weather privately for evaluation; consumes no TennisApi calls."""
import argparse
import gzip
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timedelta, timezone

from _bootstrap import ROOT
from date_window import history_window
from release_store import ReleaseStore
from download_tennis_history import read_json, write_json
from tbt.data.history_snapshot import load_partitions
from tbt.services.weather_archive import ArchiveClient, WeatherBudgetExhausted, explicit_location


def save_gzip(path, data):
    temporary = path.with_suffix('.tmp')
    with gzip.open(temporary, 'wt', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, allow_nan=False)
    temporary.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--lookback-days', type=int, default=1095)
    parser.add_argument('--max-requests', type=int, default=100)
    args = parser.parse_args()
    if os.getenv('TBT_WEATHER_RESEARCH') != 'true':
        parser.error('Set TBT_WEATHER_RESEARCH=true only for evaluation/noncommercial use; see docs/WEATHER.md')
    if not 1 <= args.max_requests <= 500:
        parser.error('Weather allowance must be 1..500; separate from TennisApi')
    start, _ = history_window(lookback_days=args.lookback_days)
    end = datetime.now(timezone.utc).date() - timedelta(days=7)
    repository = os.getenv('TBT_DATA_REPOSITORY', 'BackstageTalks/tbt-data')
    directory = ROOT / '.cache/tbt/environment'
    store = ReleaseStore(repository, 'tbt-environment-v1', directory)
    years = range(start.year, end.year + 1)
    store.download(extra_names=('locations.json', 'weather_budget.json', *(f'enviro-{y}.json.gz' for y in years)))
    history_store = ReleaseStore(repository, 'tbt-data-v1', ROOT / '.cache/tbt/history')
    history_store.download()
    matches = load_partitions(history_store.directory)
    # Separate weather provider budget, retained even after interruption.
    stamp = datetime.now(timezone.utc)
    reservations = [r for r in read_json(directory / 'weather_budget.json', [])
                    if datetime.fromisoformat(r['expires_at']) > stamp]
    if sum(r['requests'] for r in reservations) + args.max_requests > 500:
        raise SystemExit('Weather allocation exhausted for this 28h window')
    reservations.append({'requests': args.max_requests, 'expires_at': (stamp + timedelta(hours=28)).isoformat()})
    write_json(directory / 'weather_budget.json', reservations)
    store.upload([directory / 'weather_budget.json'])
    partitions = {}
    for year in years:
        path = directory / f'enviro-{year}.json.gz'
        if path.exists():
            with gzip.open(path, 'rt', encoding='utf-8') as stream:
                partitions[year] = json.load(stream)
        else:
            partitions[year] = {'schema': 1, 'source': 'Open-Meteo reanalysis',
                                'usage': 'research_only_not_pre_match_forecast', 'days': {}}
    locations = read_json(directory / 'locations.json', {})
    client = ArchiveClient(args.max_requests)
    report, changed = Counter(), set()

    def checkpoint():
        paths = []
        for year in changed:
            path = directory / f'enviro-{year}.json.gz'
            save_gzip(path, partitions[year])
            paths.append(path)
        write_json(directory / 'locations.json', locations)
        store.upload([*paths, directory / 'locations.json'])
        changed.clear()

    try:
        for match in sorted(matches, key=lambda m: m.scheduled_at, reverse=True):
            day = match.scheduled_at.date()
            if not start <= day <= end or match.indoor is True:
                continue
            location = explicit_location(match)
            if location is None:
                report['missing_explicit_city_country'] += 1
                continue
            city, country = location
            city_key = hashlib.sha256(f'{city.casefold()}|{country}'.encode()).hexdigest()[:24]
            saved = locations.get(city_key)
            if saved is None or (saved['location'] is None and
                    (stamp - datetime.fromisoformat(saved['checked_at'])).days >= 30):
                saved = {'location': client.geocode(city, country), 'checked_at': stamp.isoformat()}
                locations[city_key] = saved
            if saved['location'] is None:
                report['unresolved_or_ambiguous_city'] += 1
                continue
            key = city_key + '|' + day.isoformat()
            days = partitions[day.year]['days']
            if key not in days:
                days[key] = {'location': saved['location'], 'date': day.isoformat(),
                             'fetched_at': stamp.isoformat(), 'hourly': client.day(saved['location'], day.isoformat())}
                changed.add(day.year)
                report['downloaded_city_days'] += 1
                if report['downloaded_city_days'] % 25 == 0:
                    checkpoint()
            else:
                report['reused_city_days'] += 1
    except WeatherBudgetExhausted:
        report['budget_stopped'] = 1
    finally:
        checkpoint()
        client.client.close()
        report['weather_requests'] = client.requests
        report['tennisapi_requests'] = 0
        write_json(directory / 'environment_report.json', dict(report))
        store.upload([directory / 'environment_report.json'])
        print(json.dumps(dict(report), indent=2))


if __name__ == '__main__':
    main()
