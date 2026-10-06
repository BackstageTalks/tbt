"""Parse approved Tennis Abstract Elo/yElo report snapshots.

This parser deliberately treats each downloaded leaderboard as a point-in-time
snapshot. It never backfills a current rating into historical matches.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from html.parser import HTMLParser
from html import unescape

import pandas as pd


DATE_RE = re.compile(r"Last\s+update:\s*(\d{4}-\d{2}-\d{2})", re.I)


def _column_name(value) -> str:
    if isinstance(value, tuple):
        parts = [str(x) for x in value if str(x) and not str(x).startswith("Unnamed")]
        text = " ".join(parts)
    else:
        text = str(value)
    text = text.replace("\xa0", " ").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    return text


def _snapshot_date(html: str) -> str:
    match = DATE_RE.search(html)
    if not match:
        raise ValueError("Tennis Abstract snapshot date not found")
    return match.group(1)


class _TableParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell: list[str] | None = None

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = tag.lower()
        if tag == "table":
            self._table = []
        elif tag == "tr" and self._table is not None:
            self._row = []
        elif tag in {"th", "td"} and self._row is not None:
            self._cell = []

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"th", "td"} and self._cell is not None and self._row is not None:
            value = unescape("".join(self._cell)).replace("\xa0", " ").strip()
            self._row.append(re.sub(r"\s+", " ", value))
            self._cell = None
        elif tag == "tr" and self._row is not None and self._table is not None:
            if any(cell for cell in self._row):
                self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            if self._table:
                self.tables.append(self._table)
            self._table = None


def _strip_markdown_link(value: str) -> str:
    match = re.fullmatch(r"\[([^\]]+)\]\([^\)]+\)", value.strip())
    return match.group(1).strip() if match else value.strip()


def _split_text_row(line: str) -> list[str] | None:
    if "\t" in line:
        return [cell.replace("\xa0", " ").strip() for cell in line.split("\t")]
    stripped = line.strip()
    if stripped.startswith("|") and stripped.endswith("|"):
        return [cell.strip() for cell in stripped[1:-1].split("|")]
    return None


def _markdown_separator(row: list[str]) -> bool:
    return bool(row) and all(
        not cell or re.fullmatch(r":?-{3,}:?", cell) is not None
        for cell in row
    )


def _find_text_table(text: str, *, kind: str) -> pd.DataFrame:
    """Parse tab-delimited or Markdown-table browser/Reader fallbacks."""
    required = {"player", "elo"} if kind == "elo" else {"player", "yelo"}
    lines = text.replace("\r\n", "\n").replace("\xa0", " ").splitlines()
    for pos, line in enumerate(lines):
        header = _split_text_row(line)
        if not header:
            continue
        names = [_column_name(cell) for cell in header]
        if not required.issubset(set(names)):
            continue
        rows: list[list[str]] = []
        width = len(header)
        for raw in lines[pos + 1:]:
            if not raw.strip():
                if rows:
                    break
                continue
            row = _split_text_row(raw)
            if row is None:
                if rows:
                    break
                continue
            if _markdown_separator(row):
                continue
            if not row or not re.fullmatch(r"\d+", row[0] or ""):
                if rows:
                    break
                continue
            row = [_strip_markdown_link(cell) for cell in row]
            if len(row) < width:
                row += [""] * (width - len(row))
            elif len(row) > width:
                row = row[:width]
            rows.append(row)
        if rows:
            return pd.DataFrame(rows, columns=names)
    raise ValueError(f"No Tennis Abstract {kind} text table found")


def _find_table(html: str, *, kind: str) -> pd.DataFrame:
    parser = _TableParser()
    parser.feed(html)
    required = {"player", "elo"} if kind == "elo" else {"player", "yelo"}
    for rows in parser.tables:
        if len(rows) < 2:
            continue
        width = max(len(row) for row in rows)
        header = rows[0] + [""] * (width - len(rows[0]))
        names = [_column_name(c) for c in header]
        if not required.issubset(set(names)):
            continue
        normalized = [row + [""] * (width - len(row)) for row in rows[1:]]
        frame = pd.DataFrame(normalized, columns=names)
        return frame
    return _find_text_table(html, kind=kind)


def _numeric(frame: pd.DataFrame, columns: list[str]) -> None:
    for name in columns:
        if name in frame.columns:
            frame[name] = pd.to_numeric(frame[name], errors="coerce")


def parse_elo(html: str, *, tour: str) -> tuple[pd.DataFrame, str]:
    snapshot = _snapshot_date(html)
    frame = _find_table(html, kind="elo")
    aliases = {
        "elo_rank": "elo_rank",
        "player": "player",
        "age": "age",
        "elo": "elo",
        "helo_rank": "hard_elo_rank",
        "helo": "hard_elo",
        "celo_rank": "clay_elo_rank",
        "celo": "clay_elo",
        "gelo_rank": "grass_elo_rank",
        "gelo": "grass_elo",
        "peak_elo": "peak_elo",
        "peak_month": "peak_month",
        "atp_rank": "official_rank",
        "wta_rank": "official_rank",
        "log_diff": "log_diff",
    }
    selected = {}
    for source, target in aliases.items():
        if source in frame.columns:
            selected[target] = frame[source]
    out = pd.DataFrame(selected)
    required = {"elo_rank", "player", "elo"}
    if not required.issubset(out.columns):
        raise ValueError(f"Elo table missing required columns: {sorted(required-set(out.columns))}")
    out.insert(0, "tour", str(tour).lower())
    out.insert(0, "snapshot_date", snapshot)
    out["player"] = out["player"].astype(str).str.replace("\xa0", " ", regex=False).str.strip()
    _numeric(
        out,
        [
            "elo_rank", "age", "elo", "hard_elo_rank", "hard_elo",
            "clay_elo_rank", "clay_elo", "grass_elo_rank", "grass_elo",
            "peak_elo", "official_rank", "log_diff",
        ],
    )
    out = out[out["player"].ne("") & out["elo"].notna()].drop_duplicates("player").reset_index(drop=True)
    return out, snapshot


def parse_yelo(html: str, *, tour: str) -> tuple[pd.DataFrame, str]:
    snapshot = _snapshot_date(html)
    frame = _find_table(html, kind="yelo")
    aliases = {
        "rank": "rank",
        "player": "player",
        "wins": "wins",
        "losses": "losses",
        "yelo": "yelo",
    }
    out = pd.DataFrame({target: frame[source] for source, target in aliases.items() if source in frame.columns})
    required = {"rank", "player", "wins", "losses", "yelo"}
    if not required.issubset(out.columns):
        raise ValueError(f"yElo table missing required columns: {sorted(required-set(out.columns))}")
    out.insert(0, "tour", str(tour).lower())
    out.insert(0, "snapshot_date", snapshot)
    out["player"] = out["player"].astype(str).str.replace("\xa0", " ", regex=False).str.strip()
    _numeric(out, ["rank", "wins", "losses", "yelo"])
    out = out[out["player"].ne("") & out["yelo"].notna()].drop_duplicates("player").reset_index(drop=True)
    return out, snapshot


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--atp-elo-html", required=True)
    ap.add_argument("--wta-elo-html", required=True)
    ap.add_argument("--atp-yelo-html", required=True)
    ap.add_argument("--wta-yelo-html", required=True)
    ap.add_argument("--out-dir", required=True)
    args = ap.parse_args()

    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [
        ("atp_elo", Path(args.atp_elo_html), parse_elo, "atp"),
        ("wta_elo", Path(args.wta_elo_html), parse_elo, "wta"),
        ("atp_yelo", Path(args.atp_yelo_html), parse_yelo, "atp"),
        ("wta_yelo", Path(args.wta_yelo_html), parse_yelo, "wta"),
    ]
    reports = {}
    dates = set()
    for name, path, parser, tour in jobs:
        html = path.read_text(encoding="utf-8", errors="replace")
        frame, snapshot = parser(html, tour=tour)
        if len(frame) < 100:
            raise SystemExit(f"{name}: unexpectedly small leaderboard ({len(frame)} rows)")
        frame.to_csv(out / f"{name}.csv", index=False)
        dates.add(snapshot)
        reports[name] = {
            "rows": int(len(frame)),
            "snapshot_date": snapshot,
            "columns": list(frame.columns),
        }

    if len(dates) != 1:
        raise SystemExit(f"Tennis Abstract snapshot dates disagree: {sorted(dates)}")
    snapshot = next(iter(dates))
    report = {
        "schema": 1,
        "source": "Tennis Abstract Elo/yElo reports",
        "snapshot_date": snapshot,
        "operator_permission_confirmed": True,
        "point_in_time_snapshot": True,
        "training_eligible": False,
        "training_ineligible_reason": (
            "Current weekly snapshot only; never backfill current Elo into historical matches. "
            "Snapshots become usable point-in-time features only for matches after their snapshot date."
        ),
        "tables": reports,
    }
    (out / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
