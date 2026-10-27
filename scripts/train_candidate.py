"""Start protected training or list saved candidates using authenticated gh."""
import argparse
import json
import subprocess
from urllib.parse import quote

from training_status import get, snapshot, REPO
from wait_for_cdb_writer_idle import snapshot as writer_snapshot

WORKFLOW = "protected-frozen-cdb-candidate.yml"
DATA = "BackstageTalks/tbt-data"


def read_lock(path, *, lock_missing_ok=False):
    proc = subprocess.run(["gh", "api", "--method", "GET", path], capture_output=True, text=True)
    if proc.returncode:
        if lock_missing_ok and "HTTP 404" in proc.stderr:
            # Check repository access before interpreting a private ref 404.
            get(f"repos/{DATA}")
            return None
        raise RuntimeError("Cannot verify writer lock; training was not dispatched")
    return json.loads(proc.stdout)


def start(ref, profile, *, read=get, inspect=None, dispatch=None):
    inspect = inspect or (lambda: writer_snapshot(read_lock))
    if inspect() != "FREE":
        raise RuntimeError("CDB writer is busy; let the existing run finish")
    commit = read(f"repos/{REPO}/commits/{quote(ref, safe='')}")["sha"]
    # Dispatch uses a branch/tag; refuse if it moved during preflight.
    for status in ("queued", "in_progress", "waiting", "pending", "requested"):
        runs = read(f"repos/{REPO}/actions/workflows/{WORKFLOW}/runs?status={status}&per_page=1")
        if runs["workflow_runs"]:
            raise RuntimeError(f"Training already queued/running: {runs['workflow_runs'][0]['html_url']}")
    if read(f"repos/{REPO}/commits/{quote(ref, safe='')}")["sha"] != commit:
        raise RuntimeError("Selected ref changed during preflight; retry with a stable tag")
    command = ["gh", "workflow", "run", WORKFLOW, "--repo", REPO,
               "--ref", ref, "-f", f"training_profile={profile}"]
    if dispatch:
        dispatch(command)
    else:
        subprocess.run(command, check=True)
    return {"state": "DISPATCHED_NOT_VERIFIED", "requested_ref": ref,
            "observed_commit_before_dispatch": commit,
            "profile": profile,
            "next": "Verify actual run commit with python scripts/train_candidate.py status"}


def candidates(read=get):
    result = []
    page = 1
    while True:
        releases = read(f"repos/{DATA}/releases?per_page=100&page={page}")
        for release in releases:
            if not release["tag_name"].startswith("blinq-candidate-frozen-"):
                continue
            assets = {a["name"]: a for a in release.get("assets", [])}
            available = all(assets.get(name, {}).get("size", 0) > 0
                            for name in ("model.joblib", "training_report.json", "_tbt_bundle_manifest.json"))
            result.append({"tag": release["tag_name"], "url": release["html_url"],
                           "state": "ASSETS_PRESENT_UNVERIFIED" if available else "INCOMPLETE",
                           "release_ready": False})
        if len(releases) < 100:
            return result
        page += 1


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    start_parser = commands.add_parser("start", help="Dispatch a new protected candidate; never promote")
    start_parser.add_argument("--ref", default="main", help="Pushed branch or immutable tag; local edits are not uploaded")
    start_parser.add_argument("--profile", choices=["standard", "top-7.2.1", "accuracy-7.2.2"], default="top-7.2.1")
    status = commands.add_parser("status")
    status.add_argument("--run", type=int)
    commands.add_parser("list", help="List private frozen candidates, including incomplete attempts")
    args = parser.parse_args()
    try:
        result = (start(args.ref, args.profile) if args.command == "start" else
                  snapshot(args.run) if args.command == "status" else candidates())
        print(json.dumps(result, indent=2))
    except (RuntimeError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"BLOCKED: {exc}\n")


if __name__ == "__main__":
    main()
