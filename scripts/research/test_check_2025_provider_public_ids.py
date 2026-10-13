from pathlib import Path
import sys,unittest
sys.path.insert(0,str(Path(__file__).resolve().parent))
from check_2025_provider_public_ids import assess,norm
class Tests(unittest.TestCase):
  def make(self, id='275923',name='Carlos Alcaraz',tour='atp'):
    return {'tour':tour,'player1_id':id,'player1_name':name,'player2_id':'33','player2_name':'Other'}
  def test_two_matches_required(self):
    self.assertFalse(assess([self.make()])['result']['carlos_alcaraz']['sofascore_id_equal_to_cdb'])
  def test_matching_source_two_events(self):
    self.assertTrue(assess([self.make(),self.make()])['result']['carlos_alcaraz']['sofascore_id_equal_to_cdb'])
  def test_other_id_is_blocked(self):
    self.assertFalse(assess([self.make(id='115728'),self.make(id='115728')])['result']['carlos_alcaraz']['sofascore_id_equal_to_cdb'])
  def test_name_collision_excluded(self):
    self.assertFalse(assess([self.make(name='Other Alcaraz'),self.make(name='Other Alcaraz')])['result']['carlos_alcaraz']['sofascore_id_equal_to_cdb'])
  def test_multi_id_conflict_block(self):
    self.assertFalse(assess([self.make(),self.make(id='115728')])['result']['carlos_alcaraz']['sofascore_id_equal_to_cdb'])
  def test_tour_mismatch_block(self):
    self.assertFalse(assess([self.make(tour='wta'),self.make(tour='wta')])['result']['carlos_alcaraz']['sofascore_id_equal_to_cdb'])
  def test_shevchenko_accents(self):
    rows=[self.make(id='264344',name='Aleksandr Shevchenko'),self.make(id='264344',name='Alexander Shevchenko')]
    self.assertTrue(assess(rows)['result']['aleksandr_shevchenko']['sofascore_id_equal_to_cdb'])
  def test_djokovic(self):
    rows=[self.make(id='14882',name='Novak Djokovic'),self.make(id='14882',name='Novak Djokovic')]
    self.assertTrue(assess(rows)['result']['novak_djokovic']['sofascore_id_equal_to_cdb'])
  def test_sinner(self):
    rows=[self.make(id='206570',name='Jannik Sinner'),self.make(id='206570',name='Jannik Sinner')]
    self.assertTrue(assess(rows)['result']['jannik_sinner']['sofascore_id_equal_to_cdb'])
  def test_wta_swiatek(self):
    rows=[self.make(id='228272',name='Iga Świątek',tour='wta'),self.make(id='228272',name='Iga Swiatek',tour='wta')]
    self.assertTrue(assess(rows)['result']['iga_swiatek']['sofascore_id_equal_to_cdb'])
  def test_wta_sabalenka(self):
    rows=[self.make(id='157754',name='Aryna Sabalenka',tour='wta'),self.make(id='157754',name='Aryna Sabalenka',tour='wta')]
    self.assertTrue(assess(rows)['result']['aryna_sabalenka']['sofascore_id_equal_to_cdb'])
  def test_false_is_never_import(self):
    r=assess([self.make(),self.make()]);self.assertFalse(r['cross_provider_player_link_authorized']);self.assertEqual(r['new_CDB_cells_written'],0)
if __name__=='__main__':unittest.main()
