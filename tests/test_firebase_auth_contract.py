from types import SimpleNamespace

from tbt.services.auth import auth_provider, firebase_user_to_dict


def test_firebase_is_only_runtime_identity_provider():
    cfg = SimpleNamespace(
        firebase_project_id="blinq-182",
        firebase_client_email="server@example.iam.gserviceaccount.com",
        firebase_private_key="-----BEGIN PRIVATE KEY-----\\nkey\\n-----END PRIVATE KEY-----\\n",
    )
    assert auth_provider(cfg) == "firebase"


def test_firebase_user_record_maps_to_internal_account_shape():
    class Meta:
        creation_timestamp = 1_757_401_200_000
        last_sign_in_timestamp = 1_757_404_800_000

    class Record:
        uid = "firebase-u1"
        email = "member@example.com"
        display_name = "Member"
        custom_claims = {
            "role": "user",
            "blinq_plan": "pro",
            "blinq_status": "active",
            "blinq_avatar_variant": "w",
            "blinq_hide_ads": True,
        }
        user_metadata = Meta()

    user = firebase_user_to_dict(Record())
    assert user["id"] == "firebase-u1"
    assert user["email"] == "member@example.com"
    assert user["app_metadata"]["blinq_plan"] == "pro"
    assert user["user_metadata"]["display_name"] == "Member"
    assert user["user_metadata"]["blinq_avatar_variant"] == "w"
    assert user["user_metadata"]["blinq_hide_ads"] is True
    assert user["created_at"].endswith("+00:00")


def test_web_uses_firebase_rest_without_server_secret():
    auth_js = open("web/auth.js", encoding="utf-8").read()
    csp = open("web/staticwebapp.config.json", encoding="utf-8").read()
    assert "identitytoolkit.googleapis.com" in auth_js
    assert "securetoken.googleapis.com" in auth_js
    assert "blinq_v4_session" in auth_js
    assert "FIREBASE_PRIVATE_KEY" not in auth_js
    assert "FIREBASE_CLIENT_EMAIL" not in auth_js
    assert "identitytoolkit.googleapis.com" in csp
    assert "securetoken.googleapis.com" in csp
    assert "supabase.co" not in auth_js.lower()
    assert "supabase.co" not in csp.lower()
