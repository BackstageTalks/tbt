import hashlib,json,pathlib,sqlite3,subprocess,sys,tempfile,unittest
sys.path.insert(0,str(pathlib.Path(__file__).resolve().parent.parent/"scripts"))
import stage_dil_from_google_drive as stage
class DriveRestoreContractTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();self.root=pathlib.Path(self.t.name)
  self.source=self.root/'source.sqlite'
  with sqlite3.connect(self.source) as db:
   db.execute('CREATE TABLE canonical_matches(match_id TEXT PRIMARY KEY)')
   db.execute("INSERT INTO canonical_matches VALUES('verified-identity')")
  archive=self.root/'src.zst';subprocess.run(['zstd','-q','-f',str(self.source),'-o',str(archive)],check=True)
  self.parts=self.root/'parts';self.parts.mkdir()
  original=archive.read_bytes();(self.parts/'part001.bin').write_bytes(original)
  self.manifest=stage.checked_manifest({'schema':stage.SCHEMA,'parts':[{'filename':'part001.bin','size':len(original),'sha256':hashlib.sha256(original).hexdigest()}],
    'archive_sha256':hashlib.sha256(original).hexdigest(),'unpacked_sqlite_sha256':stage.sha(self.source),'unpacked_sqlite_bytes':self.source.stat().st_size})
 def tearDown(self):self.t.cleanup()
 def test_real_sqlite_restore_and_full_integrity(self):
  out=self.root/'isolated'/'new.sqlite';report=stage.reconstruct(self.parts,self.manifest,out)
  self.assertTrue(report['full_integrity_check'])
  self.assertEqual(report['canonical_matches'],1)
  self.assertEqual(stage.sha(out),stage.sha(self.source))
  self.assertFalse((self.root/'isolated'/'new.sqlite.archive.partial.zst').exists())
 def test_tampered_chunk_aborts_no_publish(self):
  (self.parts/'part001.bin').write_bytes(b'tampered')
  out=self.root/'isolated'/'new.sqlite'
  with self.assertRaises(ValueError):stage.reconstruct(self.parts,self.manifest,out)
  self.assertFalse(out.exists())
 def test_existing_destination_cannot_be_overwritten(self):
  out=self.root/'existing.sqlite';out.write_bytes(b'old')
  with self.assertRaises(FileExistsError):stage.reconstruct(self.parts,self.manifest,out)
  self.assertEqual(out.read_bytes(),b'old')
 def test_manifest_path_traversal_and_missing_parts_blocked(self):
  m={**self.manifest,'parts':[{**self.manifest['parts'][0],'filename':'../unsafe.sqlite'}]}
  with self.assertRaises(ValueError):stage.checked_manifest(m)
  m={**self.manifest,'parts':self.manifest['parts']*2}
  with self.assertRaises(ValueError):stage.checked_manifest(m)
 def test_external_manifest_pins_refuse_changed_archive_before_download(self):
  class FakeResponse:
   def raise_for_status(self): pass
   def json(self):return {'files':[{'name':'archive_parts_manifest.json','id':'manifest'}]}
  class FakeSession:
   def get(self,*args,**kwargs):return FakeResponse()
  original=stage._fetch_bytes
  try:
   stage._fetch_bytes=lambda *a,**kw:json.dumps(self.manifest).encode()
   with self.assertRaisesRegex(ValueError,'independently pinned digest'):
    stage.stage_drive('1crwy2Z0AoG-bApBOhZ8SKvK_gJ9T7Ypg',self.root/'blocked.sqlite',self.root/'newdir',session=FakeSession(),expected_archive_sha256='0'*64)
  finally:stage._fetch_bytes=original
  self.assertFalse((self.root/'blocked.sqlite').exists())
  self.assertFalse((self.root/'newdir').exists())
 def test_zero_partial_results_without_credentials(self):
  with self.assertRaises(ValueError):stage.stage_drive('unsafe',self.root/'sqlite',self.root/'scratch')
  self.assertFalse((self.root/'scratch').exists())
if __name__=='__main__':unittest.main()
