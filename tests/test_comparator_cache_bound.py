"""Focused cache eviction tests without Azure Functions or provider imports."""
import ast
from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "api/function_app.py").read_text(encoding="utf-8")


def _pruner(maximum=3, ttl=300):
    tree = ast.parse(SOURCE)
    function = next(node for node in tree.body
                    if isinstance(node, ast.FunctionDef) and node.name == "_prune_comparator_result_cache")
    namespace = {
        "_COMPARATOR_RESULT_CACHE": {},
        "_COMPARATOR_RESULT_TTL_SECONDS": ttl,
        "_COMPARATOR_RESULT_MAX_ENTRIES": maximum,
    }
    module = ast.Module(body=[function], type_ignores=[])
    exec(compile(module, "api/function_app.py", "exec"), namespace)
    return namespace["_COMPARATOR_RESULT_CACHE"], namespace["_prune_comparator_result_cache"]


def test_all_fresh_cache_entries_still_have_hard_limit():
    cache, prune = _pruner()
    cache.update({f"entry-{i}": (900 + i, {"value": i}) for i in range(6)})
    prune(1000.0)
    assert len(cache) == 3
    assert set(cache) == {"entry-3", "entry-4", "entry-5"}
    # Safe idempotence; frequently-used newest results remain cached.
    prune(1000.0)
    assert len(cache) == 3


def test_expired_entries_removed_without_evicting_fresh_data():
    cache, prune = _pruner()
    cache.update({"expired": (699.0, {}), "boundary": (700.0, {}),
                  "fresh-1": (800.0, {}), "fresh-2": (900.0, {})})
    prune(1000.0)
    assert set(cache) == {"boundary", "fresh-1", "fresh-2"}


def test_repeated_unique_misses_cannot_exceed_capacity():
    cache, prune = _pruner(maximum=5)
    for i in range(40):
        cache[f"query-{i}"] = (1000.0 + i, {"value": i})
        if len(cache) > 5:
            prune(1040.0)
        assert len(cache) <= 5
    assert set(cache) == {f"query-{i}" for i in range(35, 40)}


def test_pruner_is_wired_inside_result_cache_lock():
    write_block = SOURCE.split("        with _COMPARATOR_RESULT_CACHE_LOCK:", 2)[-1]
    assert "_COMPARATOR_RESULT_CACHE[cache_key] = (now_mono, result)" in write_block
    assert "_prune_comparator_result_cache(now_mono)" in write_block
