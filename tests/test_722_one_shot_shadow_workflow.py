"""Guard a single approved 7.2.2 prospective-only shadow bootstrap.

This test must never call Github, mutate releases or train a model. The
existing activation worker remains responsible for global lock and readback.
"""
from pathlib import Path


def test_one_shot_push_is_scoped_to_722_research_and_retains_manual_dispatch():
    source = Path(".github/workflows/activate-shadow-candidate.yml").read_text()
    assert "workflow_dispatch:" in source
    assert "branches: [main]" in source
    assert 'paths: [".github/workflows/activate-shadow-candidate.yml"]' in source
    assert "chore(722): one-shot verified prospective shadow activation 20261112-run-42284691497" in source
    assert "github.event_name == 'push'" in source
    assert "github.repository == 'BackstageTalks/tbt'" in source
    assert "github.ref == 'refs/heads/main'" in source

    # Pin both sides of the CAS and the source model SHA: this is deliberately
    # not a default that follows the latest mutable candidate release.
    assert "blinq-candidate-frozen-42284691497-1" in source
    assert "aa0f0ab10f08ef76f1bb793e431e460448ff7c645fb8528ba452957700215da8" in source
    assert "131a4dd71994f082bf5c041c5f7a785d581421170a44ace39de9e27c61f1de3f" in source
    assert "github.event_name == 'push' && 'true' || inputs.prospective_only || false" in source
    assert "args+=(--prospective-only --expected-source-sha256" in source

    # No added writer or model switch; existing single-writer and rollback
    # paths must remain the sole mutation route.
    assert "group: blinq-model-backup-single-writer" in source
    assert "python scripts/cdb_global_writer_lock.py acquire" in source
    assert "python scripts/activate_shadow_candidate.py" in source
    assert "python scripts/cdb_global_writer_lock.py release --if-held" in source
    assert "promote" not in source.lower()
