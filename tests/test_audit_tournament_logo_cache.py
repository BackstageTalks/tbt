import io
from zipfile import ZipFile

from scripts.audit_tournament_logo_cache import feed_ids, inventory


def test_only_numeric_provider_tournament_ids_are_included():
    data = {
        "upcoming": [
            {"tournament_logo_id": "12", "tournament_name": "A"},
            {"tournament_logo_id": "Auckland", "tournament_name": "B"},
        ],
        "markets": {"aces": [{"tournament_id": 34}, {"tournamentId": "98x"}]},
    }
    assert feed_ids(data) == {"12", "34"}


def test_archive_inventory_never_infers_licensing_or_deployment():
    raw = io.BytesIO()
    image = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    with ZipFile(raw, "w") as archive:
        archive.writestr("tournaments/12.png", image)
        archive.writestr("tournaments/34.png", image)
        archive.writestr("../unexpected", b"bad")
    raw.seek(0)
    feed = {"upcoming": [{"tournament_id": "12"}, {"tournament_id": "99"}]}
    profiles = {
        "schema": 1,
        "tournaments": {
            "12": {"logo_file": "12.png", "logo_status": "available"},
            "34": {"logo_file": "34.png"},
            "99": {},
        },
    }
    with ZipFile(raw) as archive:
        result = inventory(feed, profiles, archive)
    assert result["current_feed_ids"] == 2
    assert result["unique_audited_ids"] == 3
    assert result["unexpected_zip_members"] == 1
    rows = {row["tournament_id"]: row for row in result["rows"]}
    assert rows["12"]["status"] == "cached_valid_not_deployment_verified"
    assert rows["99"]["status"] == "never_attempted_or_not_recorded"
    assert all(not row["deployed_verified"] for row in rows.values())
    assert all(not row["license_verified_for_reuse"] for row in rows.values())
    assert len(result["duplicate_hash_groups"]) == 1


def test_reject_invalid_profile_schema():
    from pytest import raises

    with ZipFile(io.BytesIO(_zip_stub())) as archive:
        with raises(ValueError, match="schema"):
            inventory({}, {"schema": 2}, archive)


def _zip_stub():
    handle = io.BytesIO()
    with ZipFile(handle, "w"):
        pass
    return handle.getvalue()


def test_large_private_inventory_uses_file_upload_not_long_argv():
    from pathlib import Path
    workflow = (Path(__file__).resolve().parents[1] / '.github' / 'workflows' / 'tournament-logo-inventory.yml').read_text(encoding='utf-8')
    assert '--input /tmp/blinq-logo-inventory/github-upload.json' in workflow
    assert '-f content="$encoded"' not in workflow
    assert 'cmp "$file" /tmp/blinq-logo-inventory/readback.json' in workflow
