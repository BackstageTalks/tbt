"""Static versioned assets can be cached briefly; authority and HTML cannot."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CONFIG=json.loads((ROOT/"web/staticwebapp.config.json").read_text(encoding="utf-8"))
ROUTES={row["route"]:row.get("headers",{}) for row in CONFIG["routes"]}
HTML=(ROOT/"web/index.html").read_text(encoding="utf-8")


def test_static_asset_cache_never_caches_auth_or_published_state():
    assets=["/blinq-mobile.css","/blinq-mobile-visual.css","/blinq-mobile-court.css",
            "/blinq-detail.css","/blinq-daily-hub-mobile.css"]
    for path in assets:
        policy=ROUTES[path]["Cache-Control"].lower()
        assert "public" in policy and "max-age=300" in policy, path
        assert "no-store" not in policy and "immutable" not in policy, path
    for path in ["/","/index.html","/ui-config.json","/config/*","/membership-links.json",
                 "/app.js","/auth.js","/responsive.js","/blinq-app.css","/insight-media.js"]:
        assert "no-store" in ROUTES[path]["Cache-Control"].lower(), path
    for path in ["/app.js","/auth.js","/responsive.js","/blinq-app.css"]:
        assert path+"?v=" in HTML, path
    assert '/assets/blinq-loader.webp' in HTML
    assert 'id="bootSplash"' in HTML
