from pathlib import Path
import inspect
import json
from types import SimpleNamespace

from tbt.services import auth
from tbt.services.auth import auth_provider, _normalized_private_key

ROOT = Path(__file__).resolve().parents[1]


def test_rebuild_keeps_v65_dashboard_contract_and_complete_assets():
    cfg = json.loads((ROOT / "web" / "ui-config.json").read_text(encoding="utf-8"))
    assert tuple(map(int, cfg["ui_revision"].split("."))) >= (6, 5, 4)
    for name in (
        "blinq_logo.svg",
        "blinq_background.png",
        "blinq_favi.png",
        "missing_foto_m.png",
        "missing_foto_w.png",
        "rookie_m.webp",
        "rookie_w.webp",
        "pro_m.webp",
        "pro_w.webp",
        "elite_m.webp",
        "elite_w.webp",
        "goat.webp",
        "legend_m.webp",
        "legend_w.webp",
    ):
        assert (ROOT / "web" / "assets" / name).is_file(), name


def test_rebuild_keeps_probability_first_market_policy():
    source = (ROOT / "api" / "tbt" / "services" / "market_selection.py").read_text(encoding="utf-8")
    assert "PUBLICATION_MIN_PROBABILITY = 0.60" in source
    assert "PRIME_TOP_CORE_PROBABILITY = 0.68" in source
    assert "PRIME_TOP_FALLBACK_PROBABILITY = 0.65" in source
    assert "PRIME_MAX_ODDS_EXCLUSIVE = 1.50" in source
    assert "TOP_MIN_ODDS: float | None = 1.50" in source
    assert "VALUE_MIN_ODDS = 1.80" in source
    assert "VALUE_MAX_ODDS_DIFFERENCE = 0.15" in source
    assert "probability_first_odds_buckets_v10_core68_fallback65" in source


def test_firebase_runtime_dependency_and_api_routes_are_present():
    requirements = (ROOT / "api" / "requirements.txt").read_text(encoding="utf-8")
    function_app = (ROOT / "api" / "function_app.py").read_text(encoding="utf-8")
    assert "firebase-admin>=6.5,<8" in requirements
    assert 'API_VERSION = "3.5.1"' in function_app
    assert 'RELEASE = "6.5.38"' in function_app
    assert "auth_provider(settings)" in function_app
    assert 'route="v1/auth/profile"' in function_app


def test_firebase_provider_is_selected_when_server_credentials_exist():
    cfg = SimpleNamespace(
        firebase_project_id="blinq-182",
        firebase_client_email="server@example.iam.gserviceaccount.com",
        firebase_private_key="dummy",
    )
    assert auth_provider(cfg) == "firebase"



def test_runtime_auth_has_no_supabase_fallback():
    runtime_files = [
        ROOT / "api" / "function_app.py",
        ROOT / "api" / "tbt" / "config.py",
        ROOT / "api" / "tbt" / "services" / "auth.py",
        ROOT / "api" / "tbt" / "services" / "admin_accounts.py",
        ROOT / "web" / "auth.js",
        ROOT / "web" / "staticwebapp.config.json",
    ]
    combined = "\n".join(path.read_text(encoding="utf-8") for path in runtime_files).lower()
    assert "supabase" not in combined

def test_private_key_normalization_handles_azure_json_style_value():
    cfg = SimpleNamespace(firebase_private_key='"-----BEGIN PRIVATE KEY-----\\nabc\\n-----END PRIVATE KEY-----\\n"')
    value = _normalized_private_key(cfg)
    assert value.startswith("-----BEGIN PRIVATE KEY-----\n")
    assert value.endswith("-----END PRIVATE KEY-----\n")
    assert "\\n" not in value


def test_firebase_id_token_verification_checks_revocation():
    source = inspect.getsource(auth._verify_firebase_user)
    assert "check_revoked=True" in source


def test_browser_has_only_public_firebase_config_and_required_csp_hosts():
    auth_js = (ROOT / "web" / "auth.js").read_text(encoding="utf-8")
    swa = (ROOT / "web" / "staticwebapp.config.json").read_text(encoding="utf-8")
    assert "identitytoolkit.googleapis.com" in auth_js
    assert "securetoken.googleapis.com" in auth_js
    assert "FIREBASE_PRIVATE_KEY" not in auth_js
    assert "FIREBASE_CLIENT_EMAIL" not in auth_js
    assert "identitytoolkit.googleapis.com" in swa
    assert "securetoken.googleapis.com" in swa


def test_manual_deploy_ci_installs_runtime_dependencies_and_smoke_imports_api():
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "Install API runtime dependencies" in workflow
    assert "python -m pip install -r api/requirements.txt" in workflow
    assert "Smoke import Azure API" in workflow
    assert "import function_app" in workflow
