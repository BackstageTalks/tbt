from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from release_store import ReleaseStore


def main() -> None:
    repository = os.environ["TBT_DATA_REPOSITORY"]
    history_dir = ROOT / ".cache" / "tbt" / "history"
    assets_dir = ROOT / ".cache" / "tbt" / "player-assets"

    history = ReleaseStore(repository, "tbt-data-v1", history_dir)
    history.download()

    assets = ReleaseStore(repository, "tbt-player-assets-v1", assets_dir)
    names = assets._asset_names()
    if "player_profiles.json" in names:
        assets.download(extra_names=("player_profiles.json",))

    print(f"Production preflight inputs ready: history={history_dir} player_assets={assets_dir}")


if __name__ == "__main__":
    main()
