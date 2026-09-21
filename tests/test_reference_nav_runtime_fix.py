from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = (ROOT / "web" / "app.js").read_text(encoding="utf-8")


def test_render_navigation_resolves_reference_nav_locally():
    start = APP.index("function renderNavigation(){")
    block = APP[start:start + 2200]
    assert "const referenceNav=document.querySelector('.reference-navigation');" in block
    assert "if(referenceNav){" in block


def test_reference_nav_is_not_used_before_local_declaration():
    start = APP.index("function renderNavigation(){")
    block = APP[start:start + 2200]
    decl = block.index("const referenceNav=")
    use = block.index("if(referenceNav){")
    assert decl < use
