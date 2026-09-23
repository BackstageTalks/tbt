"""Upgrade level CTA and layout regression from R58 screenshot review."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_current_or_insufficient_membership_never_offers_misleading_upgrade():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    card = app.split("function renderUpgradeTierCard(", 1)[1].split(
        "function showUpgradePrompt(", 1
    )[0]
    prompt = app.split("function showUpgradePrompt(", 1)[1].split(
        "function clearPrivateWorkspaceState(", 1
    )[0]
    assert "const isCurrent=idx===currentIndex;" in card
    assert "const alreadyOwned=idx<currentIndex;" in card
    assert "if(isCurrent)" in card
    assert "else if(alreadyOwned)" in card
    assert "else if(lockedContext&&below)" in card
    assert "Neodomkne túto sekciu" in card
    assert "Aktuálny plán" in card
    assert "data-upgrade-account-route" in card
    assert "membershipHierarchy.indexOf(currentPlan)" in prompt


def test_upgrade_card_is_flex_column_without_phantom_empty_description_rows():
    css = (ROOT / "web/blinq-app.css").read_text(encoding="utf-8")
    assert "R58: offer cards use one stable column flow" in css
    r58 = css.split("R58: offer cards use one stable column flow", 1)[1]
    assert "display:flex!important;flex-direction:column!important" in r58
    assert "min-height:0!important;height:100%!important" in r58
    assert "flex:1 0 auto!important" in r58
    assert ".upgrade-tier-cta.is-disabled" in r58
    assert "pointer-events:none!important" in r58


def test_sets_market_odds_never_uses_model_projection_as_bookmaker_price():
    app = (ROOT / "web/app.js").read_text(encoding="utf-8")
    odds = app.split("function projectionOddsHtml(", 1)[1].split(
        "function dailyHubRow(", 1
    )[0]
    assert "row?.odds,row?.betting?.odds" in odds
    assert "row?.projection" not in odds
    assert "Market odds unavailable" in odds
