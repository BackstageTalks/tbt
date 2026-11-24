"""Decide whether the serialized evening workflow needs a provider call."""
from datetime import date
import base64
import json
import os
from pathlib import Path
import subprocess


def api(path, *args, optional=False):
    result = subprocess.run(["gh", "api", path, *args], capture_output=True, text=True)
    if result.returncode:
        if optional and "HTTP 404" in result.stderr:
            return None
        raise RuntimeError(result.stderr[:250])
    return json.loads(result.stdout)


def prepare(day, destination, *, request=api):
    date.fromisoformat(day)
    repo = "repos/BackstageTalks/tbt-data"
    name = f"aces-offers-{day}.json"
    release = request(repo + "/releases/tags/tbt-data-v1")
    # Paginate rather than assuming the release response includes every asset.
    page = 1
    while True:
        assets = request(f"{repo}/releases/{release['id']}/assets?per_page=100&page={page}")
        if any(asset["name"] == name for asset in assets):
            return "complete"
        if len(assets) < 100:
            break
        page += 1
    path = repo + "/contents/research/propline-evening-odds/" + day
    entries = request(path, optional=True) or []
    reports = sorted(x["name"] for x in entries if x["name"].startswith("propline-") and x["name"].endswith(".json"))
    if reports:
        item = request(path + "/" + reports[-1])
        if not item.get("content"):
            item = request(repo + "/git/blobs/" + item["sha"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(base64.b64decode(item["content"]))
        return "reuse"
    # Create-only receipt before the network call. An uncertain attempt after
    # a crash must be recovered from its artifact, never charged a second time.
    request(path + "/capture-reserved.json", "-X", "PUT", "-f",
            "message=Reserve daily PropLine board [skip ci]", "-f",
            "content=" + base64.b64encode(os.environ["GITHUB_RUN_ID"].encode()).decode())
    return "fetch"


if __name__ == "__main__":
    mode = prepare(os.environ["BETTING_DAY"], Path("reports/propline-evening/odds.json"))
    with open(os.environ["GITHUB_OUTPUT"], "a") as out:
        print("mode=" + mode, file=out)
