import csv, gzip, json, sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
from ta_tml_native_bridge import audit, ta_tourney, compare, TA_FIELDS, TML_FIELDS

class TestBridge(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.tml=self.root/'atp_2024.csv'
        self.ta=self.root/'ta.jsonl.gz'
        self.a={
          'source_tour':'atp','ta_matchid':'2024-0495-294','source_event_candidate_key':'k1',
          'source_side_a_profile_slug':'RogerFederer','source_side_b_opponent_normalized_name':'Marton Fucsovics',
          'round':'QF','perspectives':2,'source_perspectives_mirrored':True,
          'import_ready':False,'canonical_match_id':None,
        }
        self.b={
          'tourney_id':'2024-495','tourney_date':'20240226','match_num':'28',
          'round':'QF','winner_name':'Roger Federer','loser_name':'Marton Fucsovics',
          'winner_id':'F001','loser_id':'F002',
        }
        counts={}
        for i,(tk,ck) in enumerate(zip(TA_FIELDS,TML_FIELDS)):
            self.b['w_'+ck]=str(i+10);self.b['l_'+ck]=str(i+12)
            counts[tk]=i+10;counts['opp_'+tk]=i+12
        self.a['source_stats_counts']=counts
    def run_audit(self,a=None,b=None):
        a=self.a if a is None else a;b=self.b if b is None else b
        with self.tml.open('w',newline='') as f:
            out=csv.DictWriter(f,fieldnames=list(b))
            out.writeheader();out.writerow(b)
        with gzip.open(self.ta,'wt') as f:f.write(json.dumps(a)+'\n')
        return audit(self.ta,[self.tml],self.root/'out')
    def test_tourney_leading_zeroes_not_match_num(self):
        self.assertEqual(ta_tourney('2024-0495-294'),'2024-495')
        self.assertEqual(ta_tourney('2024-M-ITF-SRB-2024-001-128'),'2024-M-ITF-SRB-2024-001')
        self.assertEqual(ta_tourney('malformed'), '')
    def test_exact_and_no_write(self):
        report=self.run_audit()
        self.assertEqual(report['native_agreement_rows'],1)
        self.assertEqual(report['cdb_written_cells'],0)
        with gzip.open(self.root/'out/native_source_agreement_review.jsonl.gz','rt') as f: x=json.loads(next(f))
        self.assertEqual(x['tml_match_num'],'28')
        self.assertNotEqual(x['tml_match_num'],'294')
        self.assertFalse(x['cdb_write_authorized'])
    def test_conflict_quarantine(self):
        self.a['source_stats_counts']['aces']+=1
        report=self.run_audit()
        self.assertEqual(report['counts']['SOURCE_COUNT_CONFLICT'],1)
        self.assertEqual(report['native_agreement_rows'],0)
    def test_one_profile_not_sufficient(self):
        self.a['perspectives']=1;self.a['source_perspectives_mirrored']=False
        r=self.run_audit();self.assertEqual(r['counts']['not_mirrored_both_profiles'],1)
    def test_missing_match_num_not_linked(self):
        self.b['match_num']=''
        r=self.run_audit();self.assertEqual(r['counts']['missing_tml_native_match_num'],1)
    def test_wrong_names_not_linked(self):
        self.b['loser_name']='Unknown Person'
        r=self.run_audit();self.assertEqual(r['counts']['no_native_context_match'],1)
    def test_refuses_premature_authorization(self):
        self.a['import_ready']=True
        with self.assertRaises(ValueError):self.run_audit()

if __name__=='__main__':unittest.main()