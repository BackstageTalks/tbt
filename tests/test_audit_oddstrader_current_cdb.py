"""Read-only OddsTrader current CDB markers audit contract."""
import json

import pandas as pd
import pytest

from scripts.audit_oddstrader_current_cdb import FIELDS, PRIOR_VERIFIED_MARKERS, ODDSTRADER_SOURCE, count_markers


def test_count_published_market_and_fallback_separately():
    ids = pd.Series(["m1", "m2", "m3"])
    contexts = pd.Series([
        json.dumps({FIELDS[0]: {"quote_semantics": "unspecified_time"}}),
        json.dumps({FIELDS[0]: {}, FIELDS[1]: {"odds": 1.9}}),
        "{}",
    ])
    out = count_markers(ids, contexts)
    assert out["checked"] == 3
    assert out[FIELDS[0]] == 2
    assert out[FIELDS[1]] == 1
    assert sum(PRIOR_VERIFIED_MARKERS.values()) == 12218


@pytest.mark.parametrize("ids,contexts", [
    (["a", "a"], ["{}", "{}"]),
    (["", "b"], ["{}", "{}"]),
    (["a"], ["not json"]),
    (["a"], ["[]"]),
    (["a"], [5]),
])
def test_fail_closed_on_duplicate_or_invalid_context(ids, contexts):
    with pytest.raises(ValueError):
        count_markers(pd.Series(ids), pd.Series(contexts))


def test_omit_unknown_context_but_not_misread_market_time():
    out = count_markers(pd.Series(["a", "b"]), pd.Series([None, "{}"]))
    assert out["checked"] == 2
    assert all(out.get(field, 0) == 0 for field in FIELDS)



def test_attribution_excludes_unrelated_market_providers():
    ids = pd.Series(["m1", "m2", "m3", "m4"])
    contexts = pd.Series([
        json.dumps({FIELDS[0]: {"source": ODDSTRADER_SOURCE}}),
        json.dumps({FIELDS[0]: {"source": "other_market_provider"}, FIELDS[1]: {"source": "other_market_provider"}}),
        json.dumps({FIELDS[0]: {"source": ODDSTRADER_SOURCE}, FIELDS[1]: {"source": ODDSTRADER_SOURCE}}),
        json.dumps({FIELDS[1]: {"source": ODDSTRADER_SOURCE}}),
    ])
    data = count_markers(ids, contexts)
    assert data[FIELDS[0]] == 3 and data[FIELDS[1]] == 3
    assert data[FIELDS[0] + "_oddstrader"] == 2
    assert data[FIELDS[1] + "_oddstrader"] == 2


def test_readonly_code_never_publishes():
    from pathlib import Path
    source = (Path(__file__).resolve().parents[1] /
              "scripts/audit_oddstrader_current_cdb.py").read_text()
    for dangerous in ("upload_bundle(", "write_year_partition(", "training.fit(", "gh release create"):
        assert dangerous not in source
    assert '"production_cdb_mutated": False' in source
    assert '"model_training_performed": False' in source
