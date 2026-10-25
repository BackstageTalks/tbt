import datetime as dt, hashlib,importlib.util,json,pathlib,sqlite3,tempfile,unittest
ROOT=pathlib.Path(__file__).resolve().parent
SCRIPTS=(ROOT.parent/'scripts') if (ROOT.parent/'scripts'/'build_current_cdb_compare.py').exists() else ROOT
s=importlib.util.spec_from_file_location('export',str(SCRIPTS/'build_current_cdb_compare.py'))
f=importlib.util.module_from_spec(s);s.loader.exec_module(f)
class Tests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=pathlib.Path(self.tmp.name)
        self.years={}
        for y in [2025,2026]:
            name=f'history-{y}.parquet'
            data=b'PAR1'+str(y).encode()+b'PAR1'
            (self.path/name).write_bytes(data)
            self.years[str(y)]={'asset':name,'sha256':hashlib.sha256(data).hexdigest()}
        self.manifest={'years':self.years}; (self.path/'history_manifest.json').write_text(json.dumps(self.manifest))
        self.bundle={'files':{}}
        for name in [f'history-{y}.parquet' for y in [2025,2026]]+['history_manifest.json']:
            self.bundle['files'][name]={'sha256':f.sha256(self.path/name)}
        (self.path/'_tbt_bundle_manifest.json').write_text(json.dumps(self.bundle))
        self.rel={'tag_name':'tbt-data-v1','assets':[{'name':p.name,'id':i+5,'size':p.stat().st_size,'digest':'sha256:'+f.sha256(p)} for i,p in enumerate(self.path.iterdir()) if p.is_file()]}
    def tearDown(self):self.tmp.cleanup()
    def test_valid_source_inventory(self):
        z=f.validate_sources(self.path,self.rel,self.rel,expected_parts=2)
        self.assertEqual(z['year_count'],2)
    def test_mutated_asset_rejected(self):
        (self.path/'history-2026.parquet').write_bytes(b'PAR1corruptedPAR1')
        with self.assertRaisesRegex(ValueError,'LENGTH MISMATCH|DIGEST MISMATCH'):
            f.validate_sources(self.path,self.rel,self.rel,expected_parts=2)
    def test_release_changed_rejected(self):
        other=json.loads(json.dumps(self.rel))
        other['assets'][0]['id']+=1
        with self.assertRaisesRegex(ValueError,'RELEASE_MOVED'):
            f.validate_sources(self.path,self.rel,other,expected_parts=2)
    def test_sqlite_count_identity_and_date(self):
        p=self.path/'test.sqlite';conn=sqlite3.connect(p);conn.execute(f.SCHEMA)
        row={k:None for k in f.FIELDS}
        row.update(match_id='m'*24,tour='wta',scheduled_at=1750000000,
                   player1_id='1',player2_id='2',source_year=2025,stats_json='{}')
        self.assertEqual(f.write_rows(conn,[row],2025),1)
        self.assertEqual(conn.execute('select count(*) from cdb_matches').fetchone()[0],1)
        with self.assertRaises(sqlite3.IntegrityError):f.write_rows(conn,[row],2025)
        row['scheduled_at']=1770000000
        row['match_id']='n'*24
        with self.assertRaisesRegex(ValueError,'Date/partition disagreement'):
            f.write_rows(conn,[row],2025)
        conn.close()
if __name__=='__main__':unittest.main(verbosity=2)