"""Read-only access to private source-scoped Charting observations (NOT whole-match CDB stats).

Call only on a server after authenticated ReleaseStore download. No prediction
code imports this by default, and no canonical match-ID join is authorized.
"""
from __future__ import annotations
import gzip,hashlib,json,re
from pathlib import Path

MANIFEST="charting-observations-manifest-v1.json"
MAX_COMPRESSED=32_000_000
MAX_INFLATED=250_000_000
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda:stream.read(1<<20),b""):h.update(block)
    return h.hexdigest()

class ChartingObservations:
    def __init__(self, root: str | Path):
        self.root=Path(root).resolve()
        path=self.root/MANIFEST
        if path.is_symlink() or not path.is_file() or path.stat().st_size>4_000_000:
            raise ValueError("Private observation manifest absent/oversized")
        manifest=json.loads(path.read_text(encoding="utf8"))
        if (manifest.get("schema")!=1 or manifest.get("namespace")!="charting_observations/v1"
            or manifest.get("canonical_history_partitions_modified") is not False
            or manifest.get("canonical_statistics_changed") is not False
            or manifest.get("canonical_event_join_approved") is not False
            or manifest.get("training_model_eligible") is not False
            or set(manifest.get("assets",{}))!={"atp","wta"}):
            raise ValueError("Untrusted charting observation manifest")
        for tour,asset in manifest["assets"].items():
            name=f"charting-observations-{tour}-v1.jsonl.gz"
            if asset.get("name")!=name:raise ValueError("Invalid charting asset name")
            path=self.root/name
            if path.is_symlink() or not path.is_file() or path.stat().st_size>MAX_COMPRESSED:
                raise ValueError("Missing/oversized charting asset")
            if path.stat().st_size!=asset.get("bytes") or sha(path)!=asset.get("sha256"):
                raise ValueError("Charting sidecar SHA-256 or size mismatch")
        self.manifest=manifest

    def observations(self,source_match_id: str,*,tour: str)->list[dict]:
        """Only source-native identifiers; never query by canonical event ID."""
        if tour not in ("atp","wta") or not isinstance(source_match_id,str) or ".." in source_match_id or not re.fullmatch(r"[0-9A-Za-z_+ .-]{1,240}",source_match_id):
            raise ValueError("Invalid charting source selector")
        p=self.root/self.manifest["assets"][tour]["name"]
        found=[];count=0;length=0
        with gzip.open(p,"rt",encoding="utf-8") as stream:
            for line in stream:
                length+=len(line.encode("utf-8"))
                if length>MAX_INFLATED or not line.strip():
                    raise ValueError("Corrupt/inflated charting sidecar")
                row=json.loads(line);count+=1
                if (row.get("schema")!=1 or row.get("tour")!=tour
                    or row.get("canonical_match_id") is not None
                    or row.get("canonical_write_allowed") is not False
                    or row.get("prediction_training_allowed") is not False
                    or row.get("independent_provider_event_identity") is not False
                    or row.get("whole_match_stats_eligible") is not False
                    or row.get("observation_scope")!="charted_point_sample_unknown_completeness"):
                    raise ValueError("Untrusted charting row: canonical scope leakage")
                if row.get("source_match_id")==source_match_id:found.append(row)
        if count!=self.manifest["assets"][tour]["rows"]:
            raise ValueError("Charting sidecar row count drift")
        return found
