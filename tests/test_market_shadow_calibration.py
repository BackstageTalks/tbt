"""Focused opt-in research adapter regression tests; never activate serving."""
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from tbt.models.market_shadow_calibration import MarketShadowParams, blend_with_market

BASE=datetime(2026,11,20,12,tzinfo=timezone.utc)
CAP=BASE-timedelta(hours=3)
ISS=BASE-timedelta(hours=2)
PARAMS=MarketShadowParams(a=0.058883431874891985,b=1.5190747404944331,c=-0.12775926576102908)


def evaluate(p, f, *, captured_at=CAP, issued_at=ISS, scheduled_at=BASE):
    return blend_with_market(p,f,PARAMS,captured_at=captured_at,issued_at=issued_at,scheduled_at=scheduled_at)


def test_symmetric_under_player_swap():
    p=np.linspace(.02,.98,61)
    fair=np.linspace(.95,.05,61)
    np.testing.assert_allclose(evaluate(p,fair)+evaluate(1-p,1-fair),np.ones(len(p)),atol=1e-12)


def test_monotonic_in_model_and_market_probability():
    p=np.linspace(.05,.95,101)
    fair=np.linspace(.05,.95,101)
    assert np.all(np.diff(evaluate(p,np.full(len(p),.65)))>=-1e-13)
    assert np.all(np.diff(evaluate(np.full(len(p),.65),fair))>=-1e-13)


def test_fallback_missing_fair_and_explicit_mask():
    q,fallback=blend_with_market([.65,.77],[.72,np.nan],PARAMS,captured_at=[CAP,CAP],issued_at=[ISS,ISS],scheduled_at=[BASE,BASE],return_fallback_mask=True)
    assert fallback.tolist()==[False,True]
    assert q[1]==pytest.approx(.77)


def test_fallback_unverifiable_clock_or_after_start():
    for cap,iss,start in [(BASE+timedelta(minutes=1),ISS,BASE),
                          (CAP,BASE+timedelta(seconds=1),BASE),
                          (ISS+timedelta(seconds=1),ISS,BASE),
                          ('2026-11-20T09:00:00',ISS,BASE),
                          (None,ISS,BASE)]:
        q,mask=blend_with_market([.70],[.50],PARAMS,captured_at=cap,issued_at=iss,scheduled_at=start,return_fallback_mask=True)
        assert mask.tolist()==[True]
        assert q[0]==pytest.approx(.70)


def test_invalid_coefficients_and_misaligned_rows_fail_closed():
    with pytest.raises(ValueError):MarketShadowParams(a=-.01,b=1)
    with pytest.raises(ValueError):MarketShadowParams(a=0,b=0)
    with pytest.raises(ValueError):MarketShadowParams(a=float('nan'),b=1)
    with pytest.raises(ValueError):evaluate([.6,.7],[.6])
    with pytest.raises(ValueError):blend_with_market([.6,.7],[.6,.7],PARAMS,captured_at=[CAP],issued_at=ISS,scheduled_at=BASE)


def test_missing_timestamps_do_not_enable_market():
    q,mask=blend_with_market([.73],[.50],PARAMS,return_fallback_mask=True)
    assert q.tolist()==pytest.approx([.73])
    assert mask.tolist()==[True]


def test_model_clip_for_missing_fair():
    q,mask=blend_with_market([1.,0.],[None,None],PARAMS,return_fallback_mask=True)
    assert mask.tolist()==[True,True]
    assert q.tolist()==pytest.approx([.99,.01])
