"""Offline contract tests for the PropLine Google Drive immutable writer."""
from __future__ import annotations

import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from propline_drive_archive import archive, validated_archive, sha256


class Response:
    def __init__(self, payload=None, *, data=b"", ok=True, status=200):
        self.payload, self.data, self.ok, self.status_code = payload, data, ok, status

    def json(self):
        return self.payload

    def raise_for_status(self):
        if not self.ok:
            raise RuntimeError("HTTP failure")

    def iter_content(self, chunk_size=65536):
        yield self.data


class Session:
    def __init__(self, *, expected, existing=False, corrupt=False, refuse=False):
        self.expected, self.existing = expected, existing
        self.corrupt, self.refuse = corrupt, refuse
        self.posts = 0

    def get(self, url, **kwargs):
        if url.endswith("/files"):
            return Response({"files": [{"id": "remote-id"}] if self.existing else []})
        data = b"corrupted" if self.corrupt else self.expected
        return Response(data=data)

    def post(self, url, **kwargs):
        self.posts += 1
        if self.refuse:
            return Response({}, ok=False, status=403)
        return Response({"id": "remote-id", "name": kwargs["data"].split(
            b'"name":"', 1)[1].split(b'"', 1)[0].decode(),
            "parents": ["folder"]})


def report(day="2026-11-18"):
    return {
        "schema": 1, "source": "propline_free",
        "target_betting_day": day, "cdb_writes": 0,
        "published_picks_changed": 0, "provider_paid_calls": 0,
        "provider_requests": 1, "status": "no_exact_aces_market_available",
        "events_in_target_window": [],
    }


class DriveArchiveTests(unittest.TestCase):
    def test_validation_rejects_mismatched_day_and_unapproved_writes(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "odds.json"
            path.write_text(json.dumps(report()))
            self.assertEqual(validated_archive(path, "2026-11-18"), path.read_bytes())
            with self.assertRaises(ValueError):
                validated_archive(path, "2026-11-19")
            unsafe = report()
            unsafe["cdb_writes"] = 1
            path.write_text(json.dumps(unsafe))
            with self.assertRaises(ValueError):
                validated_archive(path, "2026-11-18")

    def test_multi_request_per_event_archive_provenance_is_bounded(self):
        with TemporaryDirectory() as temp:
            path = Path(temp) / "odds.json"
            item = report()
            item["events_in_target_window"] = [{"event_id": "123"}]
            item["provider_requests"] = 2
            item["provider_event_requests"] = 1
            path.write_text(json.dumps(item))
            self.assertEqual(validated_archive(path, "2026-11-18"), path.read_bytes())
            item["provider_requests"] = 3
            path.write_text(json.dumps(item))
            with self.assertRaises(ValueError):
                validated_archive(path, "2026-11-18")

    def test_create_and_readback(self):
        data = json.dumps(report()).encode()
        s = Session(expected=data)
        r = archive(s, data=data, day="2026-11-18", run_id="1234", folder="folder")
        self.assertEqual(r["status"], "PERSISTED_VERIFIED_READBACK")
        self.assertIn(sha256(data)[:16], r["name"])
        self.assertEqual(s.posts, 1)

    def test_repeated_same_bytes_skip_mutation_after_readback(self):
        data = json.dumps(report()).encode()
        s = Session(expected=data, existing=True)
        r = archive(s, data=data, day="2026-11-18", run_id="1234", folder="folder")
        self.assertEqual(r["status"], "already_verified")
        self.assertEqual(s.posts, 0)

    def test_corrupted_remote_data_rejected(self):
        data = json.dumps(report()).encode()
        with self.assertRaises(ValueError):
            archive(Session(expected=data, existing=True, corrupt=True),
                    data=data, day="2026-11-18", run_id="1234", folder="folder")

    def test_drive_write_rejection_does_not_report_success(self):
        data = json.dumps(report()).encode()
        with self.assertRaises(RuntimeError):
            archive(Session(expected=data, refuse=True),
                    data=data, day="2026-11-18", run_id="1234", folder="folder")

    def test_rejects_bad_run_id(self):
        with self.assertRaises(ValueError):
            archive(Session(expected=b""), data=b"", day="2026-11-18",
                    run_id="../escape", folder="folder")


if __name__ == "__main__":
    unittest.main()
