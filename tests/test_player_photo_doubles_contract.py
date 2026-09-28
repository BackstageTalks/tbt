"""Presentation regression: photos for published picks and honest doubles pairs."""
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from enrich_player_cards import _current_players
from prepare_feed import _feed_player_ids, _merge_player_profiles


def test_enrichment_covers_published_only_players_and_doubles_members():
    feed = {
        "upcoming": [{"tour": "ATP", "confidence": .81,
                      "player1": {"id": "11", "name": "Upcoming"},
                      "player2": {"id": "12", "name": "Opponent"}}],
        "top_daily_picks": [{"tour": "WTA", "confidence": .73,
                             "player1": {"id": "21", "name": "Published"},
                             "player2": {"id": "22", "name": "Published opponent"}}],
        "doubles_picks": [{"tour": "ATP", "prediction_family": "doubles",
                           "confidence": .78,
                           "player1": {"id": "901", "name": "A / B", "members": [
                               {"id": "31", "name": "A"}, {"id": "32", "name": "B"}]},
                           "player2": {"id": "902", "name": "C / D", "members": [
                               {"id": "41", "name": "C"}, {"id": "42", "name": "D"}]}}],
        "results": [{"tour": "WTA", "player1": {"id": "51", "name": "Settled"},
                     "player2": {"id": "52", "name": "Settled opponent"}}],
    }
    found = _current_players(feed)
    ids = [row["id"] for row in found]
    assert set(ids) == {"11", "12", "21", "22", "31", "32", "41", "42", "51", "52"}
    assert "901" not in ids and "902" not in ids
    assert ids.index("21") < ids.index("11")  # published picks get photo priority


def test_deployment_attaches_each_doubles_members_own_image():
    feed = {"doubles_picks": [{"prediction_family": "doubles",
             "player1": {"id": "901", "name": "A / B",
                         "members": [{"id": "31", "name": "A"}, {"id": "32", "name": "B"}]},
             "player2": {"id": "902", "name": "C / D",
                         "members": [{"id": "41", "name": "C"}, {"id": "42", "name": "D"}]}}]}
    assert {"31", "32", "41", "42"} <= _feed_player_ids(feed)
    profiles = {id: {"photo_file": id + ".webp"} for id in ("31", "32", "41", "42")}
    _merge_player_profiles(feed, profiles, set(id + ".webp" for id in profiles))
    players = feed["doubles_picks"][0]["player1"]["members"]
    assert [p["photo_url"] for p in players] == [
        "/assets/players/31.webp", "/assets/players/32.webp"]


def test_fallbacks_are_real_local_assets_and_team_ui_is_not_team_headshot():
    for sex in ("m", "w"):
        path = ROOT / "web" / "assets" / f"missing_foto_{sex}.webp"
        assert path.is_file() and path.stat().st_size > 1000
    app = (ROOT / "web" / "app.js").read_text()
    css = (ROOT / "web" / "blinq-app.css").read_text()
    assert "function sideAvatarHtml" in app
    assert "function doublesMembers" in app
    assert "sideAvatarHtml(row,player,side,'hub-avatar')" in app
    assert "sideAvatarHtml(r,p1,'player1','hub-avatar')" in app
    assert "doubles-pair-avatar" in css
    assert "using-initials .player-avatar-initials" in css
