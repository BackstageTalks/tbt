"""Release 7.0 API smoke contracts kept in pytest as well as GitHub Actions."""
import function_app
from tbt.services.auth import auth_provider, update_firebase_profile, verify_user


def test_api_exports_health_and_auth_smoke_targets():
    assert callable(function_app.health)
    assert callable(auth_provider)
    assert callable(update_firebase_profile)
    assert callable(verify_user)
