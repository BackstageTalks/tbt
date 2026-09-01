from __future__ import annotations

import json

from _bootstrap import ROOT  # noqa: F401
from tbt.services.sync import refresh_predictions


if __name__ == "__main__":
    print(json.dumps(refresh_predictions(), indent=2))
