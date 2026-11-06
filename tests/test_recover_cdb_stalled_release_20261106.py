"""Offline fail-closed contracts for one-shot CDB recovery (no GitHub or provider)."""
import pytest

from recover_cdb_stalled_release_20261106 import (
    PINNED, TRANSIENT, YEAR_ASSET, assert_pinned,
    verify_inventory_consistency,
)


def _assets():
    base = {
        name: {"id": ident, "digest": "sha256:" + digest, "size": size}
        for name, (ident, digest, size) in PINNED.items()
    }
    base["history-2026.parquet"] = {
        "id": 987, "digest": "sha256:" + "a" * 64, "size": 99
    }
    return base


def _metadata(assets):
    history = {"years": {
        "2022": {"asset": YEAR_ASSET, "rows": 100,
                 "sha256": "f" * 64, "bytes": 101},
        "2026": {"asset": "history-2026.parquet", "rows": 101,
                 "sha256": "a" * 64, "bytes": 99},
    }}
    bundle = {"files": {
        name: {"sha256": ("f" * 64 if name == YEAR_ASSET else
                         assets[name]["digest"][7:]),
               "bytes": (101 if name == YEAR_ASSET else assets[name]["size"])}
        for name in (
            "history-2022.parquet", "history-2026.parquet",
            "history_manifest.json", "_tbt_bundle_manifest.json"
        ) if name != "_tbt_bundle_manifest.json"
    }}
    return history, bundle


def test_exact_frozen_release_is_required_before_mutation():
    assets = _assets()
    assert_pinned(assets)
    assert len(TRANSIENT) == 3
    assets[YEAR_ASSET]["digest"] = "sha256:" + "0" * 64
    with pytest.raises(RuntimeError, match="changed since incident audit"):
        assert_pinned(assets)


def test_unknown_journal_blocks_before_mutation():
    assets = _assets()
    assets["blinq-txn-" + "a" * 32 + ".json"] = {
        "id": 777, "digest": "sha256:" + "1" * 64, "size": 120
    }
    with pytest.raises(RuntimeError, match="Unexpected CDB transactions"):
        assert_pinned(assets)


def test_only_pinned_2022_checksum_mismatch_is_allowed_before_repair():
    assets = _assets()
    history, bundle = _metadata(assets)
    assert verify_inventory_consistency(
        assets, history, bundle, permitted_mismatch=frozenset({YEAR_ASSET})
    ) == (2, 3)
    with pytest.raises(RuntimeError, match="Unrecognized CDB checksum mismatch"):
        verify_inventory_consistency(
            assets, history, bundle, permitted_mismatch=frozenset()
        )


def test_other_history_mismatch_is_not_repaired_by_guessing():
    assets = _assets()
    history, bundle = _metadata(assets)
    assets["history-2026.parquet"]["digest"] = "sha256:" + "e" * 64
    with pytest.raises(RuntimeError, match="Unrecognized CDB checksum mismatch"):
        verify_inventory_consistency(
            assets, history, bundle, permitted_mismatch=frozenset({YEAR_ASSET})
        )


def test_missing_history_partition_is_fatal():
    assets = _assets()
    history, bundle = _metadata(assets)
    del assets["history-2026.parquet"]
    with pytest.raises(FileNotFoundError):
        verify_inventory_consistency(
            assets, history, bundle, permitted_mismatch=frozenset({YEAR_ASSET})
        )
