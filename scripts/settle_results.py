from __future__ import annotations

import json

from _bootstrap import ROOT  # noqa: F401
from tbt.services.sync import sync_current_year_results


if __name__ == "__main__":
    print(json.dumps(sync_current_year_results(), indent=2))
