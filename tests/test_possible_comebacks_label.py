from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_prime_public_label_is_possible_comebacks():
    app = (ROOT / "web" / "app.js").read_text(encoding="utf-8")
    assert "Comebacks" in app
    assert "COMEBACKS" in app
    assert "Short Odds" not in app
    assert "SHORT ODDS" not in app
