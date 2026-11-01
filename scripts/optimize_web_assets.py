#!/usr/bin/env python3
"""Deterministic whitespace-only optimization of committed frontend assets.

Source files stay readable in Git. The deploy job optimizes the staging copy
only, after all regression tests and before deployment fingerprinting.
No bundling, identifier mangling or syntax compression is permitted.
"""
import argparse
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ESBUILD = "esbuild@0.25.12"
ASSETS = ("app.js", "blinq-app.css")


def build(web: Path, output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    stats = {}
    release = json.loads((web / "release.json").read_text(encoding="utf-8"))
    patch = str(release["patch"]).replace("736-", "7.3.6-", 1)
    visual = str(release["visual_revision"])
    for name in ASSETS:
        source = web / name
        dest = output_dir / name
        subprocess.run(
            ["npx", "--yes", ESBUILD, str(source),
             "--minify-whitespace", "--target=esnext", "--charset=utf8",
             "--legal-comments=none", "--log-level=error",
             f"--outfile={dest}"],
            check=True, cwd=ROOT,
        )
        if name.endswith(".css"):
            css = dest.read_text(encoding="utf-8")
            # Azure read-back uses these deliberately preserved revision markers.
            dest.write_text(
                f"/* BlinQ runtime patch {patch} */\n"
                f"/* BlinQ visual revision {visual} */\n" + css,
                encoding="utf-8",
            )
        else:
            # esbuild drops the original app.js revision comment. Reattach the
            # release marker after optimization so strict live read-back can
            # verify the exact visual revision without changing JS behaviour.
            js = dest.read_text(encoding="utf-8")
            dest.write_text(
                f"/* BlinQ visual revision: {visual} */\n" + js,
                encoding="utf-8",
            )
            subprocess.run(["node", "--check", str(dest)], check=True, cwd=ROOT)
        before, after = source.stat().st_size, dest.stat().st_size
        if not 0 < after < before:
            raise RuntimeError(f"{name}: optimization failed size check {before} -> {after}")
        stats[name] = {"source_bytes": before, "optimized_bytes": after,
                       "reduction_percent": round(100 * (before - after) / before, 2)}
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--web", type=Path, default=ROOT / "web")
    parser.add_argument("--output-dir", type=Path,
                        default=Path(tempfile.gettempdir()) / "blinq-optimized-web")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    results = build(args.web, args.output_dir)
    if args.apply:
        for name in ASSETS:
            shutil.copyfile(args.output_dir / name, args.web / name)
    print(json.dumps({"mode": "deploy" if args.apply else "test",
                      "assets": results}, sort_keys=True))


if __name__ == "__main__":
    main()
