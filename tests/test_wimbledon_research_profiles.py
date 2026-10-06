from pathlib import Path

from scripts.build_wimbledon_research_profiles import build


HEADER = (
    "Tournament,Year,Event,Round,Match,Court,Player1,Player2,Set,Game,Tiebreak,Point,"
    "Server,Winner,Score1,Score2,Service,ServeDirection,S_and_V,ReturnHand,SpeedMPH,"
    "ShotMain,ShotDetail,RallyCount,ShotWinErr,FirstServeTimestamp,SecondServeTimestamp,"
    "EndofPointTimestamp\n"
)


def test_build_wimbledon_profile_is_server_oriented_and_research_safe(tmp_path: Path):
    source = tmp_path / "w14 PbP MS LS R1-R3.csv"
    source.write_text(
        HEADER
        + "Wimbledon,2014,MS,1,1,1,A.Player,B.Player,1,1,0,1,1A,1,0,0,1,W,True,FH,120,3,0,1,1,,,\n"
        + "Wimbledon,2014,MS,1,1,1,A.Player,B.Player,1,1,0,2,2A,2,0,0,2,C,False,BH,95,6,0,2,1,,,\n"
        + "Wimbledon,2014,MS,1,1,1,A.Player,B.Player,1,1,0,3,1A,2,0,0,0,B,False,FH,,5,0,0,2,,,\n",
        encoding="utf-8",
    )
    rows = build([source])
    by_player = {row["player"]: row for row in rows}

    assert by_player["A.Player"]["service_points"] == 2
    assert by_player["A.Player"]["first_speed_n"] == 1
    assert by_player["A.Player"]["first_speed_mean_mph"] == "120.0"
    assert by_player["A.Player"]["ace_count"] == 1
    assert by_player["A.Player"]["double_fault_count"] == 1
    assert by_player["A.Player"]["serve_and_volley_count"] == 1

    assert by_player["B.Player"]["service_points"] == 1
    assert by_player["B.Player"]["second_speed_n"] == 1
    assert by_player["B.Player"]["second_speed_mean_mph"] == "95.0"
