"""Pre-fit checks for the opt-in 7.2.1 probability candidate."""
from __future__ import annotations

import numpy as np
import pandas as pd


def input_diagnostics(partitions, feature_names):
    report = {}
    for name, frame in partitions.items():
        groups = {"all": frame}
        groups.update({str(tour): rows for tour, rows in frame.groupby("tour")})
        report[name] = {}
        for tour, rows in groups.items():
            columns = {}
            for feature in feature_names:
                values = pd.to_numeric(rows[feature], errors="coerce")
                finite = np.isfinite(values.to_numpy(dtype=float))
                valid = values[finite]
                columns[feature] = {
                    "finite_rows": int(finite.sum()),
                    "distinct": int(valid.nunique()),
                    "nonzero_rows": int((valid != 0).sum()),
                    "variance": float(valid.var(ddof=0)) if len(valid) else None,
                }
            report[name][tour] = {"rows": len(rows), "features": columns}
    return report


def require_informative_inputs(report):
    # This prevents fitting another model with dead rank/serve/return inputs.
    # Nonzero variance is only an availability gate, not a quality guarantee.
    errors = []
    for partition in ("train", "calibration"):
        for tour in ("atp", "wta"):
            group = report.get(partition, {}).get(tour, {})
            features = group.get("features", {})
            if not group.get("rows"):
                errors.append(f"{partition}/{tour}: no rows")
                continue
            for names in (("rank_advantage", f"{tour}_hist_rank_advantage"),
                          ("serve_quality_diff",), ("return_quality_diff",)):
                if not any(features.get(n, {}).get("distinct", 0) > 1
                           and (features.get(n, {}).get("variance") or 0) > 0
                           for n in names):
                    errors.append(f"{partition}/{tour}: dead {' or '.join(names)}")
            if any(v["finite_rows"] != group["rows"] for v in features.values()):
                errors.append(f"{partition}/{tour}: nonfinite inputs")
    if errors:
        raise ValueError("7.2.1 training input gate failed: " + "; ".join(errors))
