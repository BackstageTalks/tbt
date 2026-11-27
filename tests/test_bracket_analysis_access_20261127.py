"""Owner 27.11: Admin per-level switch for Analysis inside the bracket."""
import function_app as fa

ACC = lambda plan: {"plan": plan, "status": "active", "role": "user"}


def test_falls_back_to_comparator_rules_without_explicit_map():
    ui = {"dashboard": {"comparator": {"plans": {"elite": True}}}}
    assert fa._comparator_access(ACC("elite"), ui, "bracket_analysis")[0] is True
    assert fa._comparator_access(ACC("pro"), ui, "bracket_analysis")[0] is False


def test_explicit_map_wins_even_if_comparator_differs():
    ui = {"dashboard": {"comparator": {"plans": {"legend": True}},
                        "bracket_analysis": {"plans": {"rookie": False, "pro": False, "elite": True,
                                                       "legend": False, "goat": False}}}}
    assert fa._comparator_access(ACC("elite"), ui, "bracket_analysis")[0] is True
    assert fa._comparator_access(ACC("legend"), ui, "bracket_analysis")[0] is False
    # The standalone Comparator keeps its own rules.
    assert fa._comparator_access(ACC("legend"), ui)[0] is True


def test_empty_selection_disables_all_but_admin():
    ui = {"dashboard": {"bracket_analysis": {"plans": {k: False for k in ("rookie", "pro", "elite", "legend", "goat")}}}}
    assert fa._comparator_access(ACC("goat"), ui, "bracket_analysis")[0] is False
    assert fa._comparator_access({"role": "admin"}, ui, "bracket_analysis")[0] is True
