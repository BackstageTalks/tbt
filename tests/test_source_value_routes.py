import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('routes',Path(__file__).resolve().parents[1]/'scripts/audit_source_value_routes.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)

class RoutesTests(unittest.TestCase):
    def test_opponent_orientation(self):
        v,e,error=m.derive({'p1_first_serve_win':.75,'p2_second_serve_win':.4})
        self.assertIsNone(error)
        self.assertEqual(v,{'p2_first_return_win':.25,'p1_second_return_win':.6})
        self.assertEqual(e['p2_first_return_win']['field'],'p1_first_serve_win')
    def test_existing_and_conflicting_values(self):
        self.assertEqual(m.derive({'p1_first_serve_win':.75,'p2_first_return_win':.25})[0],{})
        self.assertEqual(m.derive({'p1_first_serve_win':.75,'p2_first_return_win':.4})[2],'contradictory_complements')
    def test_invalid_rates_and_counts_not_derived(self):
        for x in (True,'75%',float('nan'),float('inf'),75,-1):
            self.assertEqual(m.derive({'p1_first_serve_win':x})[2],'invalid_rate')
        self.assertEqual(m.derive({'p1_aces':4,'p1_break_points_won':3})[0],{})
    def test_valid_boundaries(self):
        self.assertEqual(m.derive({'p1_second_serve_win':0})[0]['p2_second_return_win'],1)
        self.assertEqual(m.derive({'p2_second_serve_win':1})[0]['p1_second_return_win'],0)
    def test_historical_namespace(self):
        r=dict(round='F',tourney_id='2020-1',match_num='1',winner_name='Player A',loser_name='Player B')
        self.assertNotEqual(m.historical_id('atp','atp_matches_2020.csv',r)[0],m.historical_id('wta','wta_matches_2020.csv',r)[0])
        self.assertNotEqual(m.historical_id('atp','atp_matches_2020.csv',r)[0],m.historical_id('atp','atp_matches_futures_2020.csv',r)[0])
if __name__=='__main__':unittest.main()
