from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
APP=(ROOT/'web'/'app.js').read_text(encoding='utf-8')
CSS=(ROOT/'web'/'blinq-app.css').read_text(encoding='utf-8')

def test_account_filter_hidden_rows_override_grid_css():
    assert '.admin-simple-user-list .admin-simple-user-row[hidden]' in CSS
    assert '.admin-simple-user-list .admin-filter-empty[hidden]' in CSS
    assert 'display:none!important;' in CSS
    assert 'row.hidden=!visible.has(String(row.dataset.adminUser))' in APP

def test_account_search_empty_state_and_sort_remain_available():
    for field in ('adminUserSearch','adminUserLevelFilter','adminUserStatusFilter',
                  'adminUserSort','adminFilteredCount','adminUserFilterEmpty'):
        assert field in APP
    assert "if(t.id==='adminUserSort'){uf.sort=t.value;rerenderAdmin();adminApplyUserFilters();return;}" in APP
