from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_initial_tab_respects_public_deep_links():
    source = (ROOT / "static" / "app.js").read_text(encoding="utf-8")

    assert "window.location.hash === '#crisis-map'" in source
    assert "return 'crisis-map'" in source
    assert "window.location.hash === '#sitrep'" in source
    assert "return 'sitrep'" in source


def test_auth_initialization_preserves_requested_tab():
    source = (ROOT / "static" / "map" / "map-init.js").read_text(encoding="utf-8")

    assert source.count("switchTab(window.initialTabFromLocation());") == 2
    assert "switchTab('home');" not in source
