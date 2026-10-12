import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from scripts.normalize_hf_atp import prepare, fraction, normalize_url, stats_for_side

class TestNormalizer(unittest.TestCase):
    def test_fraction(self):
        self.assertEqual(fraction('75%(75/100)'), 0.75)
        self.assertIsNone(fraction('90%(10/20)'))
        self.assertIsNone(fraction('0%(0/0)'))
        self.assertIsNone(fraction('70%'))

    def test_url(self):
        self.assertEqual(normalize_url('https://www.atptour.com/en/scores/match-stats/archive/2023/580/ms001'), ('https://www.atptour.com/en/scores/match-stats/archive/2023/580/ms001', 2023))
        self.assertIsNone(normalize_url('https://other.com/en/scores/match-stats/archive/2023/580/ms001'))

    def test_ytd_and_invalid_service_games_excluded(self):
        stats, bad = stats_for_side({'match_Aces_p1':'7','match_Double_Faults_p1':'0', 'match_Service_Games_Played_p1':'0', 'ytd_Aces_p1':'900', 'match_1st_Serve_Points_Won_p1':'82%(54/66)'}, 'p1')
        self.assertEqual(stats, {'aces':7.0,'double_faults':0.0,'first_serve_win':54/66})
        self.assertFalse(bad)

    def test_archive_dedup_and_fail_closed(self):
        row = dict(player1='Novak Djokovic',player2='Stefanos Tsitsipas',winner='Novak Djokovic',round='Finals -',stats_url='https://www.atptour.com/en/scores/match-stats/archive/2023/580/ms001',match_Aces_p1='7',match_Aces_p2='15',match_Double_Faults_p1='3',match_Double_Faults_p2='3',match_Service_Points_Won_p1='75%(75/100)',match_Return_Points_Won_p2='25%(25/100)',match_Service_Points_Won_p2='65%(69/106)',match_Return_Points_Won_p1='35%(37/106)', ytd_Aces_p1='100')
        header=list(row)
        def csv_bytes(items):
            b=io.StringIO();w=csv.DictWriter(b,fieldnames=header);w.writeheader();w.writerows(items);return b.getvalue().encode()
        with tempfile.TemporaryDirectory() as d:
            zipname=Path(d)/'raw.zip'
            with zipfile.ZipFile(zipname,'w') as z:
                z.writestr('2023/a.csv',csv_bytes([row]))
                z.writestr('duplicate.csv',csv_bytes([row]))
            report=prepare(zipname,Path(d)/'out')
            self.assertEqual(report['counts']['quarantined_observations'],1)
            self.assertEqual(report['counts']['duplicate_csv_members'],1)
            self.assertEqual(report['writer_approved_fields'],0)
            records=[json.loads(x) for x in (Path(d)/'out/quarantined-observations.jsonl').read_text().splitlines()]
            self.assertFalse(records[0]['import_ready'])
            self.assertNotIn('ytd_Aces',records[0]['stats_p1'])
            self.assertEqual(records[0]['stats_p1']['aces'],7)

    def test_conflicting_duplicate_url_drops_both(self):
        base=dict(player1='A',player2='B',winner='A',round='Finals -',stats_url='https://www.atptour.com/en/scores/match-stats/archive/2023/580/ms001', match_Aces_p1='1',match_Aces_p2='2')
        c=dict(base,match_Aces_p1='9')
        with tempfile.TemporaryDirectory() as d:
            b=io.StringIO();w=csv.DictWriter(b,fieldnames=list(base));w.writeheader();w.writerows([base,c]);p=Path(d)/'raw.csv';p.write_text(b.getvalue())
            r=prepare(p,Path(d)/'out');self.assertEqual(r['counts']['quarantined_observations'],0)

if __name__=='__main__':
    unittest.main()
