from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'web/app.js').read_text(encoding='utf-8')
CSS=(ROOT/'web/blinq-app.css').read_text(encoding='utf-8')

def test_esa_rows_do_not_use_generic_match_detail():
    assert "if(sourceTab==='ace'||sourceTab==='double_faults')" in APP
    assert "openAceProjection(current)" in APP
    assert 'data-hub-market="${escapeHtml(sourceTab)}"' in APP

def test_esa_detail_is_projection_specific_and_hides_missing_stats():
    assert 'function aceProjectionDetailHtml' in APP
    assert 'Missing serve or return statistics are intentionally hidden.' in APP
    assert 'visibleRows=rows.filter' in APP
    assert '.ace-detail-grid' in CSS

def test_esa_tab_has_no_forced_detail_column():
    assert "if(tab==='ace'||tab==='double_faults')return ['#','ČAS','TURNAJ','ZÁPAS','PREDIKCIA','PROJEKCIA','ISTOTA'];" in APP
