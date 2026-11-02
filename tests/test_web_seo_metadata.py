"""Basic public HTML metadata stays in the head without guessing production origin."""
from pathlib import Path

HTML = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")


def test_homepage_has_one_basic_seo_and_open_graph_description():
    head = HTML.split("</head>", 1)[0]
    for token in ('name="description"', 'property="og:type"',
                  'property="og:title"', 'property="og:description"',
                  'name="twitter:card"'):
        assert head.count(token) == 1, token
    assert 'content="website"' in head
    assert 'content="summary"' in head
    # Do not assert an unverified Azure/custom-domain canonical URL.
