"""Regression: one shared BlinQ image on page root; data surfaces stay dark."""
from pathlib import Path


def test_shared_admin_backdrop_and_dark_data_surfaces():
    root = Path(__file__).resolve().parents[1] / "web"
    css = (root / "blinq-app.css").read_text(encoding="utf-8")
    html = (root / "index.html").read_text(encoding="utf-8")
    section = css.split("/* BlinQ shared homepage artwork:", 1)[1]
    assert "body#blinqPremium.blinq-admin {" in section
    assert 'var(--blinq-page-bg' in section
    assert 'url("/assets/blinq_page_background.webp")' in section
    assert "body#blinqPremium.blinq-admin .admin-workarea" in section
    assert "rgba(4,22,24,.94)" in section
    assert ".route-panel" in section
    assert "admin-backdrop=1" in html
    assert "tab-order=1" in html
    assert "account-activity=2" in html
    assert "blinq-mobile.css?v=7360&mobile=20261009-43" in html
