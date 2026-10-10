"""Prevent canonical release writers from bypassing the cross-repository lock."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"

WRITERS = (
    "alimoh89-preparation.yml",
    "cdb-identity-reconcile.yml",
    "data.yml",
    "drive-pbpx-canonical-enrichment.yml",
    "kaggle-hwaitt-history-enrichment.yml",
    "kaggle-wta-2016-2017-odds.yml",
    "nightly-data-maintenance.yml",
    "offline-uploaded-history-enrichment.yml",
    "offline-uploaded-odds.yml",
    "research-source-finalize.yml",
    "research-source-integration.yml",
    "tennis-data-historical-odds.yml",
    "training-data-enrichment.yml",
    "training-db-rebuild.yml",
    "valuebet-market-history.yml",
    "verify-usopen-serve-sidecar.yml",
    "wimbledon-1992-1995-link.yml",
    "wta-rank-gapfill.yml",
)


def test_every_known_cdb_writer_obtains_and_releases_global_lock():
    for name in WRITERS:
        path = ROOT / name
        contents = path.read_text(encoding="utf-8")
        assert "python scripts/cdb_global_writer_lock.py acquire" in contents, name
        assert "python scripts/cdb_global_writer_lock.py release --if-held" in contents, name
        assert "        if: always()" in contents, name
        # GitHub retains only one pending run per concurrency.group even when
        # cancel-in-progress=false. The global tag lock is the serializer.
        assert "github.run_id" in contents.split("jobs:", 1)[0], name
        assert "group: tbt-history-data-writer" not in contents, name


def test_main_data_pipeline_never_cancels_while_owner():
    text = (ROOT / "data.yml").read_text(encoding="utf-8")
    assert "cancel-in-progress: false" in text
    assert "[replace-stale-data-run]" not in text
