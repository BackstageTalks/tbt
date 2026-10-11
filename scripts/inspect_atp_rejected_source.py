#!/usr/bin/env python3
"""Read-only, no-provider-network diagnostic for one SHA-pinned ATP checkpoint.

Reads rejected *.unverified.html.gz pages in memory; emits COUNTS ONLY.
Never prints raw HTML, match IDs, player data, URLs or API tokens.
"""
import argparse
import gzip
import hashlib
import io
import json
import re
import tarfile
from pathlib import Path

MAX_CAPTURE = 4_000_000
MAX_RAW = 4_000_000

FEATURES = {
    "blocked_or_denied": (r"access denied|forbidden|request blocked|captcha|just a moment|"
                          r"not authorized|too many requests"),
    "client_rendered_shell": (r"__next_data__|__next_f|webpackchunk_n_e|"
                              r"__nuxt__|_next/static|react-root|data-reactroot"),
    "embedded_data_script": (r'<script[^>]+type\s*=\s*["\']application/(?:json|ld\+json)["\']'),
    "serve_stat_terms": (r"\b(?:aces?|double faults?|break points?|"
                         r"first serve|second serve|1st serve|2nd serve)\b"),
    "score_terms": (r"\b(?:sets?|games?|winner|score)\b"),
}


def inspect_html(html):
    if not isinstance(html, str):
        raise TypeError("Expected decoded HTML")
    text = re.sub(r"<script\b[^>]*>.*?</script\s*>", "", html, flags=re.I | re.S)
    text = re.sub(r"<style\b[^>]*>.*?</style\s*>", "", text, flags=re.I | re.S)
    stripped = re.sub(r"<[^>]*>", " ", text)
    stripped = re.sub(r"\s+", " ", stripped).strip()
    features = {name: bool(re.search(pattern, html, flags=re.I | re.S))
                for name, pattern in FEATURES.items()}
    return {
        "html_bytes": len(html.encode("utf-8")),
        "visible_characters_rough": len(stripped),
        "digit_count_visible_rough": sum(ch.isdigit() for ch in stripped),
        **features,
    }


def inspect_checkpoint(path, digest):
    expected = "sha256:" + hashlib.sha256(Path(path).read_bytes()).hexdigest()
    if digest.lower() != expected.lower():
        raise ValueError("Pinned SHA-256 mismatch: refuse private checkpoint")
    samples = []
    with tarfile.open(path, "r:gz") as tar:
        for member in tar:
            if not member.name.endswith(".unverified.html.gz"):
                continue
            if (not member.isfile() or member.issym() or member.islnk()
                    or not member.name.startswith("data/atptour/match_stats/")
                    or member.size > MAX_RAW or len(samples) >= 25):
                raise ValueError("Unsafe or unexpectedly many rejected ATP captures")
            item = tar.extractfile(member)
            if item is None:
                raise ValueError("Unreadable rejected capture")
            raw = item.read(MAX_RAW + 1)
            if len(raw) > MAX_RAW:
                raise ValueError("Rejected capture exceeds bound")
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as f:
                html = f.read(MAX_CAPTURE + 1)
            if len(html) > MAX_CAPTURE:
                raise ValueError("Inflated rejected HTML exceeds bound")
            samples.append(inspect_html(html.decode("utf-8", errors="replace")))
    fields = list(FEATURES)
    report = {
        "sha256_verified": True,
        "rejected_captures": len(samples),
        "max_html_bytes": max((r["html_bytes"] for r in samples), default=0),
        "max_visible_characters_rough": max(
            (r["visible_characters_rough"] for r in samples), default=0),
        "max_visible_digits_rough": max(
            (r["digit_count_visible_rough"] for r in samples), default=0),
        "feature_counts": {name: sum(bool(s[name]) for s in samples) for name in fields},
        "provider_requests": 0,
        "production_cdb_modified": False,
        "model_trained": False,
    }
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--checkpoint", required=True)
    p.add_argument("--sha256", required=True)
    args = p.parse_args()
    report = inspect_checkpoint(args.checkpoint, args.sha256)
    print("REJECTED_ATP_HTML_DIAGNOSTIC", json.dumps(report, sort_keys=True))
    if report["rejected_captures"] == 0:
        raise SystemExit("No rejected HTML capture in checkpoint; cannot diagnose source")


if __name__ == "__main__":
    main()
