from scripts.parse_tennis_abstract_elo import parse_elo, parse_yelo


def test_parse_elo_snapshot():
    html = """
    <html><body>Last update: 2026-09-28
    <table>
      <tr><th>Elo Rank</th><th>Player</th><th>Age</th><th>Elo</th><th>hElo Rank</th><th>hElo</th><th>cElo Rank</th><th>cElo</th><th>gElo Rank</th><th>gElo</th><th>Peak Elo</th><th>Peak Month</th><th>ATP Rank</th><th>Log diff</th></tr>
      <tr><td>1</td><td>Alpha Player</td><td>24.5</td><td>2200.0</td><td>1</td><td>2180.0</td><td>2</td><td>2100.0</td><td>3</td><td>2050.0</td><td>2250.0</td><td>2026-05</td><td>2</td><td>-0.3</td></tr>
    </table></body></html>
    """
    frame, snapshot = parse_elo(html, tour="atp")
    assert snapshot == "2026-09-28"
    assert frame.loc[0, "player"] == "Alpha Player"
    assert frame.loc[0, "elo"] == 2200.0
    assert frame.loc[0, "hard_elo"] == 2180.0
    assert frame.loc[0, "official_rank"] == 2


def test_parse_yelo_snapshot():
    html = """
    <html><body>Updated weekly. Last update: 2026-09-28
    <table>
      <tr><th>Rank</th><th>Player</th><th>Wins</th><th>Losses</th><th>yElo</th></tr>
      <tr><td>1</td><td>Beta Player</td><td>44</td><td>3</td><td>2323.0</td></tr>
    </table></body></html>
    """
    frame, snapshot = parse_yelo(html, tour="wta")
    assert snapshot == "2026-09-28"
    assert frame.loc[0, "player"] == "Beta Player"
    assert frame.loc[0, "wins"] == 44
    assert frame.loc[0, "yelo"] == 2323.0



def test_parse_elo_reader_tab_snapshot():
    text = """Title: Tennis Abstract: ATP Elo Ratings

Updated weekly(ish). Last update: 2026-09-28
Elo\u00a0Rank\tPlayer\tAge\tElo\t\u00a0\u00a0\tATP\u00a0Rank\tLog\u00a0diff
1\tJannik\u00a0Sinner\t24.8\t2296.9\t\t1\t0
"""
    frame, snapshot = parse_elo(text, tour="atp")
    assert snapshot == "2026-09-28"
    assert frame.loc[0, "player"] == "Jannik Sinner"
    assert frame.loc[0, "elo"] == 2296.9


def test_parse_yelo_reader_markdown_snapshot():
    text = """Title: Tennis Abstract: WTA Season yElo Ratings

Updated weekly(ish). Last update: 2026-09-28
| Rank | Player | Wins | Losses | yElo |
| ---: | :--- | ---: | ---: | ---: |
| 1 | [Aryna Sabalenka](https://example.test/player) | 44 | 3 | 2323.0 |
"""
    frame, snapshot = parse_yelo(text, tour="wta")
    assert snapshot == "2026-09-28"
    assert frame.loc[0, "player"] == "Aryna Sabalenka"
    assert frame.loc[0, "yelo"] == 2323.0
