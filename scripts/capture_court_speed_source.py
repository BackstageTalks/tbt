"""Capture a court-speed source for future use; never backdate availability."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

URL = 'https://www.tennisabstract.com/reports/atp_surface_speed.html'


def capture(directory):
    with urlopen(Request(URL, headers={'User-Agent': 'BlinQ research source snapshot'}), timeout=60) as response:
        body = response.read()
    if b'ATP Surface Speed Ratings' not in body:
        raise ValueError('Unexpected source content')
    received = datetime.now(timezone.utc)
    folder = Path(directory)/received.strftime('%Y%m%dT%H%M%S%fZ')
    folder.mkdir(parents=True, exist_ok=False)
    (folder/'source.html').write_bytes(body)
    proof = {'source_url': URL, 'tour': 'atp', 'available_at_utc': received.isoformat(),
             'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body),
             'historical_backfill_eligible': False,
             'policy': 'Observed availability only. Event dates and displayed update dates are not pre-match publication proof. Raw snapshot is not model-ready.'}
    (folder/'manifest.json').write_text(json.dumps(proof, indent=2), encoding='utf-8')
    if hashlib.sha256((folder/'source.html').read_bytes()).hexdigest() != proof['sha256']:
        raise RuntimeError('Snapshot read-back mismatch')
    return folder, proof


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    folder, proof = capture(args.output)
    print(json.dumps({'path': str(folder), **proof}))
