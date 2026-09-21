"""Compatibility import for the canonical point-in-time feature builder.

The production implementation lives in :mod:`tbt.models.feature_builder`.
This module remains only because a small number of audit/legacy callers import
``tbt.services.feature_builder``.  Re-exporting keeps those import paths stable
without maintaining two 2k+ line copies that can silently diverge.
"""
from __future__ import annotations

from ..models.feature_builder import *  # noqa: F401,F403
from ..models.feature_builder import FEATURE_NAMES, FeatureBuilder, stats_surface_key

__all__ = ["FeatureBuilder", "FEATURE_NAMES", "stats_surface_key"]
