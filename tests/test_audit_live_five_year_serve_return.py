"""Synthetic negative tests for five-year private-only canonical audit."""
import importlib.util
from pathlib import Path

def load():
    import sys
    path=Path(__file__).resolve().parents[1]/'scripts/audit_live_five_year_serve_return.py'
    spec=importlib.util.spec_from_file_location('live_sr_audit',path)
    m=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m

def test_rate_validation():
    m=load()
    assert m.valid(0) and m.valid(1.0) and m.valid(0.7)
    assert not m.valid(True) and not m.valid(None) and not m.valid(1.01)
    assert not m.valid(float('nan')) and not m.valid(float('inf'))

def test_exact_release_asset_set_and_digests():
    m=load()
    expected=('history_manifest.json','_tbt_bundle_manifest.json',*(f'history-{y}.parquet' for y in m.YEARS))
    items=[{'name':n,'digest':'sha256:'+('a'*64),'size':10} for n in expected]
    assert len(m.release_assets({'assets':items}))==7
    import pytest
    with pytest.raises(ValueError):m.release_assets({'assets':items[:-1]})
    with pytest.raises(ValueError):m.release_assets({'assets':items+[items[0]]})
    with pytest.raises(ValueError):m.release_assets({'assets':items[:-1]+[dict(items[-1],digest='sha256:bad')]})

def test_exact_complement_contract():
    m=load()
    assert len(m.PAIRS)==6 and len(set(m.PAIRS))==6
    assert ('p1_first_serve_win','p2_first_return_win') in m.PAIRS
    assert ('p2_second_serve_win','p1_second_return_win') in m.PAIRS
