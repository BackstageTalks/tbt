"""Prove WTA rank workflow de-dup does not merge distinct canonical CDB writers."""
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[1] / ".github" / "workflows"
PAIRS = (
    ("blinq-wta2021-2022-guarded-rank-import.yml", (2021, 2022),
     "wta-2021-2022-verified-ranks-"),
    ("blinq-wta2023-2024-guarded-rank-import.yml", (2023, 2024),
     "wta-oldyear-verified-ranks-"),
)
REUSABLE = "reusable-wta-oldrank-publish.yml"


def test_original_year_triggers_and_workflow_concurrency_are_preserved():
    for name, years, concurrency in PAIRS:
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        other = set((2021, 2022, 2023, 2024)) - set(years)
        assert "  pull_request:" in text
        assert "  push:" in text and "    branches: [main]" in text
        assert "  cancel-in-progress: false" in text
        assert concurrency in text
        assert "secrets: inherit" in text
        assert f"uses: ./.github/workflows/{REUSABLE}" in text
        assert f"year_matrix: '[{years[0]}, {years[1]}]'" in text
        assert f"      - .github/workflows/{REUSABLE}" in text
        assert "scripts/import_wta2023_2024_verified_rank_exact_cells.py" in text
        for year in years:
            assert f".github/wta{year}-rank-publish-request.json" in text
        for year in other:
            assert f".github/wta{year}-rank-publish-request.json" not in text
        assert "cdb_global_writer_lock.py acquire" not in text


def test_reusable_writer_still_requires_verified_evidence_and_global_lock():
    text = (WORKFLOWS / REUSABLE).read_text(encoding="utf-8")
    assert "  workflow_call:" in text
    assert "year: ${{ fromJSON(inputs.year_matrix) }}" in text
    assert "github.event_name == 'push' && github.ref == 'refs/heads/main'" in text
    assert "max-parallel: 1" in text
    assert "r[\"year\"] == int(os.environ[\"SOURCE_YEAR\"])" in text
    for action in (
        "configure(r)",
        "--mode dry-run",
        "--mode write",
        "--mode verify",
        "scripts/cdb_global_writer_lock.py acquire --wait-seconds 1800",
        "scripts/cdb_global_writer_lock.py verify",
        "before_upload=freshness",
        "WTA_RANK_CDB_FULL_REMOTE_READBACK_PASS",
        "existing_nonnull_cells_overwritten",
        "Persist private verified provenance",
        "scripts/cdb_global_writer_lock.py release --if-held",
    ):
        assert action in text, action
    assert "      - name: Release global CDB lock on all outcomes\n        if: always()" in text
