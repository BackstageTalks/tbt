"""Prevent canonical release writers from bypassing the cross-repository lock."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".github" / "workflows"

WRITERS = (
    "alimoh89-preparation.yml",
    "cdb-identity-reconcile.yml",
    "cdb-service-complement-write.yml",
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


def test_lock_contract_checks_current_private_main_not_old_working_branch():
    contents = (ROOT / "cdb-global-writer-validation.yml").read_text(encoding="utf-8")
    assert "repository: BackstageTalks/tbt-data" in contents
    assert "ref: main" in contents
    assert "ref: fix/cdb-global-single-writer-20261010" not in contents
    assert "cmp scripts/cdb_global_writer_lock.py private-data/scripts/cdb_global_writer_lock.py" in contents


def test_pairwise_push_dryrun_never_falls_through_to_writer_approval():
    text = (ROOT / "cdb-service-pairwise-guarded.yml").read_text(encoding="utf-8")
    assert 'or request.get("mode") == "dry-run":' in text
    assert 'request.get("approved_by_operator") is False' in text
    assert 'raise SystemExit(0)' in text
    assert 'assert request.get("mode") == "write"' in text
    assert 'assert request.get("approved_by_operator") is True' in text
    assert '--isolate-provider-collisions --expected-provider-quarantine 6' in text
    assert 'assert r["quarantined_rows_proven_unchanged"] == 6' in text
