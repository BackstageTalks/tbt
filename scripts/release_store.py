import json
import re
import subprocess
from pathlib import Path

def gh(*args):
    result = subprocess.run(["gh", *map(str, args)], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"GitHub CLI operation failed: {result.stderr.strip()[:500]}")
    return result.stdout


class ReleaseStore:
    def __init__(self, repository, tag, directory):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("Expected owner/repository")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+", tag):
            raise ValueError("Invalid release tag")
        self.repository, self.tag, self.directory = repository, tag, Path(directory)
        info = json.loads(gh("repo", "view", repository, "--json", "visibility"))
        if info.get("visibility") != "PRIVATE":
            raise ValueError("Training data destination must be PRIVATE")
        # Listing avoids interpreting arbitrary auth errors as a missing release.
        releases = json.loads(gh("api", f"repos/{repository}/releases?per_page=100"))
        if not any(r.get("tag_name") == tag for r in releases):
            gh("release", "create", tag, "--repo", repository, "--title", "TBT private tennis history",
               "--notes", "Compact training partitions and resumable download progress. No API credentials.")
        self.directory.mkdir(parents=True, exist_ok=True)

    def download(self, extra_names=()):
        assets = json.loads(gh("release", "view", self.tag, "--repo", self.repository, "--json", "assets"))["assets"]
        for asset in assets:
            name = asset["name"]
            if name in extra_names or name in {"history_manifest.json", "download_progress.json", "request_budget.json"} or re.fullmatch(r"history-\d{4}\.parquet", name):
                gh("release", "download", self.tag, "--repo", self.repository, "--pattern", name,
                   "--dir", self.directory, "--clobber")

    def upload(self, paths):
        paths = [str(p) for p in paths if Path(p).is_file()]
        if paths:
            gh("release", "upload", self.tag, *paths, "--repo", self.repository, "--clobber")


