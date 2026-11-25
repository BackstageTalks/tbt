import copy, random
from tbt.services import entitlements as e


def _tree(depth=0):
    if depth > 3:
        return random.choice(["x", 1, 2.5, None, True])
    return {"a": [_tree(depth + 1) for _ in range(3)], "b": {"c": _tree(depth + 1)}, "s": "t", "n": None}


def test_fast_copy_equals_deepcopy_and_is_detached():
    random.seed(1)
    src = [_tree() for _ in range(20)]
    out = e.deepcopy(src)
    assert out == copy.deepcopy(src)
    out[0]["a"].append("changed"); out[0]["b"]["c"] = "changed"
    assert src[0]["a"][-1] != "changed" and src[0]["b"]["c"] != "changed"


def test_non_json_types_fall_back():
    class X: pass
    x = X()
    out = e.deepcopy({"x": x, "t": (1, [2])})
    assert out["x"] is not x and out["t"] == (1, [2])
