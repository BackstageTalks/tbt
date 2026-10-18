from pathlib import Path

from tbt.providers.shared_budget import (
    GLOBAL_CEILING,
    PROVIDER_PLAN_LIMIT,
    PROVIDER_RESERVE,
    PURPOSE_CAPS,
    RESET_HOUR,
    RESET_MINUTE,
)


DOC = Path("docs/LIVE_SHARED_API_BUDGET_ROLLOUT.md")


def test_shared_api_budget_documentation_matches_runtime_contract():
    text = DOC.read_text(encoding="utf-8")

    assert f"**{PROVIDER_PLAN_LIMIT:,} requests per provider billing day**" in text
    assert f"**{GLOBAL_CEILING:,} request global ceiling**" in text
    assert f"**{PROVIDER_RESERVE:,} requests (5%)**" in text
    assert f"**{RESET_HOUR:02d}:{RESET_MINUTE:02d} Europe/Bratislava**" in text

    labels = {
        "live": "LIVE Radar",
        "match": "Match Status",
        "refresh": "Refresh (including presentation enrichment)",
        "history": "History/backfill opportunistic ceiling",
    }
    for purpose, cap in PURPOSE_CAPS.items():
        assert f"| {labels[purpose]} | {cap:,} |" in text

    assert f"| **Combined, hard** | **{GLOBAL_CEILING:,}** |" in text
    assert f"| **Provider reserve kept untouched** | **{PROVIDER_RESERVE:,}** |" in text
    assert f"| **Provider plan** | **{PROVIDER_PLAN_LIMIT:,}** |" in text
