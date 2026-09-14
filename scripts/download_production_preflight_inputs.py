from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from release_store import ReleaseStore


def main() -> int:
    repository = os.environ['TBT_DATA_REPOSITORY']
    history_dir = Path('.cache/tbt/history')
    assets_dir = Path('.cache/tbt/player-assets')

    history = ReleaseStore(repository, 'tbt-data-v1', history_dir)
    history.download()

    assets = ReleaseStore(repository, 'tbt-player-assets-v1', assets_dir)
    names = set(assets._asset_names())
    if 'player_profiles.json' in names:
        assets.download(extra_names=('player_profiles.json',))

    print(f'Production preflight inputs ready: history={history_dir} player_assets={assets_dir}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
