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
    # Reproduce the original ATP collector's selector precedence without
    # outputting any text content. This disambiguates empty <main> from
    # browser-only pages and from nonempty stats outside <main>.
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    main = soup.select_one("main")
    stats_node = soup.select_one(".atp_match-stats")
    body = soup.body
    first = main or stats_node or body
    def condensed(n):
        return n.get_text(" ", strip=True) if n else ""
    a, b, c, selected = [condensed(n) for n in (main, stats_node, body, first)]
    nonempty_rows = sum(1 for tr in soup.select("table tr")
                        if any(cell.get_text(" ", strip=True)
                               for cell in tr.select("th,td")))
    table_labels = bool(re.search(
        r"\b(?:aces?|double faults?|break points?|first serve|second serve)\b",
        " ".join(x.get_text(" ", strip=True) for x in soup.select("table")),
        re.I))
    return {
        "main_present": main is not None,
        "main_visible_chars": len(a),
        "stats_node_present": stats_node is not None,
        "stats_node_visible_chars": len(b),
        "body_visible_chars": len(c),
        "original_selector_visible_chars": len(selected),
        "table_count": len(soup.select("table")),
        "nonempty_table_rows": nonempty_rows,
        "table_contains_serve_labels": table_labels,
        "body_serve_terms": bool(re.search(FEATURES["serve_stat_terms"], c, re.I)),
        "original_selector_serve_terms":
            bool(re.search(FEATURES["serve_stat_terms"], selected, re.I)),
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
        "dom_selector_counts": {
            "main_present": sum(x["main_present"] for x in samples),
            "stats_node_present": sum(x["stats_node_present"] for x in samples),
            "main_empty_but_body_nonempty": sum(
                x["main_present"] and x["main_visible_chars"] == 0
                and x["body_visible_chars"] > 100 for x in samples),
            "selector_lost_body_stats_terms": sum(
                x["body_serve_terms"] and not x["original_selector_serve_terms"]
                for x in samples),
            "table_count": sum(x["table_count"] for x in samples),
            "nonempty_table_rows": sum(x["nonempty_table_rows"] for x in samples),
            "serve_labeled_tables": sum(x["table_contains_serve_labels"]
                                       for x in samples),
        },
        "largest_body_chars": max((x["body_visible_chars"] for x in samples),default=0),
        "largest_selected_chars": max(
            (x["original_selector_visible_chars"] for x in samples),default=0),
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
