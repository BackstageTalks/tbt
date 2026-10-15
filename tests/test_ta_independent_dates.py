import json
from pathlib import Path
from tempfile import TemporaryDirectory
from scripts.parse_tennis_abstract_elo_independent import build

def sample(date,kind):
    header=("<tr><th>Elo Rank</th><th>Player</th><th>Elo</th></tr>"
            if kind=="elo" else
            "<tr><th>Rank</th><th>Player</th><th>Wins</th><th>Losses</th><th>yElo</th></tr>")
    rows="".join(
        (f"<tr><td>{i}</td><td>Test Player {i}</td><td>{1600+i}</td></tr>"
         if kind=="elo" else
         f"<tr><td>{i}</td><td>Test Player {i}</td><td>8</td><td>6</td><td>{1600+i}</td></tr>")
        for i in range(1,112))
    return f"Last update: {date}<table>{header}{rows}</table>"

def test_independent_ta_effective_dates():
    sources={
        "atp_elo":sample("2026-10-05","elo"),
        "wta_elo":sample("2026-10-12","elo"),
        "atp_yelo":sample("2026-10-12","yelo"),
        "wta_yelo":sample("2026-10-05","yelo"),
    }
    with TemporaryDirectory() as dest:
        out=Path(dest)
        report=build(sources,out)
        assert report["training_eligible"] is False
        assert report["all_boards_same_date"] is False
        assert report["snapshot_dates"]["atp_elo"]=="2026-10-05"
        assert report["snapshot_dates"]["wta_elo"]=="2026-10-12"
        assert all((out/f"{key}.csv").is_file() for key in sources)
        saved=json.loads((out/"report.json").read_text())
        assert saved["snapshot_dates"]==report["snapshot_dates"]
