import importlib.util
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest

HERE=Path(__file__).resolve().parents[1]/"scripts"/"review_tml_atptour_three_way_event.py"
spec=importlib.util.spec_from_file_location("three_way",HERE)
mod=importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class OfficialEventWitnessTest(unittest.TestCase):
    def setUp(self):
        self.source={"tourney_id":"2025-580","tourney_date":"20250113",
          "match_num":"300","tourney_name":"Australian Open","surface":"Hard",
          "winner_id":"S0AG","loser_id":"Z355","round":"F","score":"6-3 7-6(4) 6-3","best_of":"5"}
        self.official={"source":"atptour",
          "source_match_id":"atptour:2025:580:ms001",
          "source_tournament_id":"atptour:tournament:580",
          "source_url":"https://www.atptour.com/en/scores/archive/australian-open/580/2025/results",
          "round":"Final - Rod Laver Arena",
          "sides":[
            {"players":[{"name":"Jannik Sinner","atp_player_id":"S0AG"}],"scores":["6","7","6"],"winner_marker":True},
            {"players":[{"name":"Alexander Zverev","atp_player_id":"Z355"}],"scores":["3","6 4","3"],"winner_marker":False}
          ]}
        self.ids={"S0AG":"111","Z355":"222"}
        self.match=SimpleNamespace(tour="atp",player1_id="111",player2_id="222",winner_id="111",
          tournament="Australian Open",surface="hard",round_name="Final",best_of=5,
          scheduled_at=datetime(2025,1,26,tzinfo=timezone.utc),
          stats={f"p{i}_set{n}_games":v for n,ss in enumerate([(6,3),(7,6),(6,3)],1) for i,v in enumerate(ss,1)})
    def test_official_native_match_and_complete_set_tape(self):
        self.assertTrue(mod.official_compatible(self.source,self.official))
        self.assertTrue(mod.canonical_compatible(self.source,self.match,self.ids))
    def test_no_hash_replacement_for_native_official_match(self):
        from copy import deepcopy
        obj=deepcopy(self.official)
        obj["source_match_id"]="atptour:2025:580:listing-123456"
        self.assertFalse(mod.official_compatible(self.source,obj))
    def test_official_tiebreak_must_equal_original(self):
        from copy import deepcopy
        obj=deepcopy(self.official)
        obj["sides"][1]["scores"][1]="6 2"
        self.assertFalse(mod.official_compatible(self.source,obj))
    def test_official_player_and_event_ids_not_names(self):
        from copy import deepcopy
        obj=deepcopy(self.official)
        obj["sides"][0]["players"][0]["atp_player_id"]="WRONG"
        self.assertFalse(mod.official_compatible(self.source,obj))
        obj=deepcopy(self.official)
        obj["source_tournament_id"]="atptour:tournament:999"
        self.assertFalse(mod.official_compatible(self.source,obj))
    def test_canonical_missing_one_set_is_not_proof(self):
        from copy import deepcopy
        m=deepcopy(self.match)
        m.stats.pop("p2_set2_games")
        self.assertFalse(mod.canonical_compatible(self.source,m,self.ids))
    def test_canonical_wrong_winner_and_tournament_fail(self):
        from copy import deepcopy
        m=deepcopy(self.match);m.winner_id="222"
        self.assertFalse(mod.canonical_compatible(self.source,m,self.ids))
        m=deepcopy(self.match);m.tournament="Other Tournament"
        self.assertFalse(mod.canonical_compatible(self.source,m,self.ids))
    def test_canonical_rejects_hidden_extra_set(self):
        from copy import deepcopy
        m=deepcopy(self.match);m.stats["p1_set4_games"]=6
        self.assertFalse(mod.canonical_compatible(self.source,m,self.ids))
    def test_canonical_rejects_temporal_drift(self):
        from copy import deepcopy
        m=deepcopy(self.match)
        m.scheduled_at=datetime(2025,2,15,tzinfo=timezone.utc)
        self.assertFalse(mod.canonical_compatible(self.source,m,self.ids))

if __name__=="__main__":
    unittest.main()
