from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prime_public_label_is_acca():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "prime:'ACCA'" in app
    assert "prime:'COMEBACKS'" not in app
    assert "Short Odds" not in app
    assert "SHORT ODDS" not in app
