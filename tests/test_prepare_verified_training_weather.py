"""Offline tests of checksum-verified weather asset restore; no GitHub/provider calls."""
import csv
import gzip
import hashlib
import io

import pytest

from scripts import prepare_verified_training_weather as subject


def weather_payload(*, lead="24"):
    out = io.StringIO()
    fields = [
        "match_id", "scheduled_at", "forecast_lead_hours",
        "forecast_reference", "source", "temperature_c",
        "relative_humidity_pct", "surface_pressure_hpa",
        "wind_speed_kmh", "wind_gusts_kmh",
    ]
    writer = csv.DictWriter(out, fieldnames=fields)
    writer.writeheader()
    for i in range(1001):
        writer.writerow({
            "match_id": f"match-{i}", "scheduled_at": "2024-10-01T12:00:00Z",
            "forecast_lead_hours": lead,
            "forecast_reference": "previous_day1",
            "source": "open-meteo-previous-runs", "temperature_c": "18",
            "relative_humidity_pct": "55", "surface_pressure_hpa": "1015",
            "wind_speed_kmh": "10", "wind_gusts_kmh": "15",
        })
    return gzip.compress(out.getvalue().encode("utf-8"))


def configure(monkeypatch, binary, *, expected=None):
    class Release:
        def __init__(self, repo, tag, root):
            assert tag == subject.RELEASE and repo == "BackstageTalks/tbt-data"
            self.root = root

        def download(self, **kwargs):
            assert subject.ASSET in kwargs["required_names"]
            (self.root / subject.ASSET).write_bytes(binary)

    monkeypatch.setattr(subject, "ReleaseStore", Release)
    monkeypatch.setattr(subject, "_source_manifest", lambda repo: {
        "downloaded": [{
            "asset": subject.ASSET,
            "sha256": expected or hashlib.sha256(binary).hexdigest(),
            "bytes": len(binary),
        }]
    })


def test_restores_exact_gz_forecast_with_zero_provider_calls(monkeypatch, tmp_path):
    configure(monkeypatch, weather_payload())
    csv_file = tmp_path / "weather.csv"
    report = subject.restore_weather(
        "BackstageTalks/tbt-data", tmp_path / "sources", csv_file
    )
    assert report["status"] == "verified"
    assert report["rows"] == 1001
    assert report["provider_requests"] == 0
    assert report["output_csv_sha256"] == hashlib.sha256(csv_file.read_bytes()).hexdigest()


def test_refuses_changed_source_hash(monkeypatch, tmp_path):
    configure(monkeypatch, weather_payload(), expected="0" * 64)
    with pytest.raises(ValueError, match="SHA-256 mismatch"):
        subject.restore_weather("BackstageTalks/tbt-data", tmp_path / "s", tmp_path / "out.csv")


def test_refuses_non_24_hour_forecast(monkeypatch, tmp_path):
    configure(monkeypatch, weather_payload(lead="0"))
    target = tmp_path / "out.csv"
    with pytest.raises(ValueError, match="lead"):
        subject.restore_weather("BackstageTalks/tbt-data", tmp_path / "s", target)
    assert not target.exists()
