"""Fail-closed comparator rank-history publication regression."""
import ast
from pathlib import Path
from types import SimpleNamespace


def _rank_gate():
    source = Path("scripts/build_comparator_artifact.py").read_text(encoding="utf-8")
    parsed = ast.parse(source)
    functions = [node for node in parsed.body if isinstance(node, ast.FunctionDef)
                 and node.name == "_rank_inputs_required"]
    assert len(functions) == 1
    namespace = {
        "ATP_RANK_HISTORY_FEATURE_NAMES": ("atp_hist_rank_advantage",),
        "WTA_RANK_HISTORY_FEATURE_NAMES": ("wta_hist_rank_advantage",),
    }
    exec(compile(ast.Module(body=functions, type_ignores=[]), "<rank_gate>", "exec"), namespace)
    return namespace["_rank_inputs_required"], source


def test_comparator_rank_gate_matches_production_feature_contract():
    required, _ = _rank_gate()
    assert required(SimpleNamespace(feature_names=["atp_hist_rank_advantage"]))
    assert required(SimpleNamespace(feature_names=["wta_hist_rank_advantage"]))
    assert required(SimpleNamespace(feature_names=["elo_diff", "wta_hist_rank_advantage"]))
    assert not required(SimpleNamespace(feature_names=["elo_diff"]))
    assert not required(SimpleNamespace(feature_names=None))


def test_comparator_builder_requires_certified_rank_sources_and_readback():
    _, source = _rank_gate()
    assert "from rank_feature_inputs import load_rank_feature_inputs" in source
    assert "load_rank_feature_inputs(" in source
    assert "cache / \"rank-feature-inputs\", matches" in source
    assert "atp_rank_history=atp_rank_history" in source
    assert "wta_rank_history=wta_rank_history" in source
    assert 'rank_report.get("status") != "verified"' in source
    assert '"atp_rank_required_present"' in source
    assert '"wta_rank_required_present"' in source
    assert "prediction_store.upload_bundle([out])" in source
    assert "verify_store = ReleaseStore(" in source
