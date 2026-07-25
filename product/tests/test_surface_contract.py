"""The surface↔server contract (Slice 6.7).

The slice exists because the engine had silently outrun the page: four endpoints
the page never called and seven overview fields it ignored, for weeks. Nothing
failed — the data was simply invisible.

These tests make that failure loud. They are deliberately crude (they read the UI
source as text) because the alternative is a browser test rig, and the honest
trade is: catch the *contract* drift cheaply in CI, verify the *rendering* by
hand against a real vault.
"""

import pathlib
import re

import pytest

WEB = pathlib.Path(__file__).resolve().parents[1] / "viva" / "web"
UI_SRC = WEB / "ui" / "src"


def _ui_text() -> str:
    if not UI_SRC.is_dir():
        pytest.skip("UI source not present")
    return "\n".join(p.read_text() for p in UI_SRC.rglob("*.js*"))


def _overview_keys() -> set[str]:
    """The keys `service.overview` puts in its payload."""
    src = (WEB / "service.py").read_text()
    body = src[src.index("def overview("):src.index("def _income_breakdown")]
    return set(re.findall(r'^\s+"([a-z_]+)":', body, re.M))


def _server_endpoints() -> set[str]:
    return set(re.findall(r'"(/api/[a-z-]+)"', (WEB / "server.py").read_text()))


# Fields the page deliberately does not render, each with a reason. Adding to
# this list is a decision; forgetting a field is not.
DELIBERATELY_UNRENDERED = {
    "nature",        # per-movement detail; the aggregate view is what a person reads
    "uncategorized_count",  # superseded by the question queue's own count
    "review_count", "transfer_review_count", "paystub_review_count",
    "unknown_merchant_count",  # the four old card counters — the queue ranks instead
    "other_holds",   # surfaced AS QUESTIONS by the queue, not as a separate list
}


def test_every_overview_field_is_rendered_or_deliberately_dropped():
    """The gap that started this slice: `positions`, `provisional_spending` and
    friends sat in the payload for weeks with nothing showing them."""
    ui = _ui_text()
    missing = sorted(k for k in _overview_keys()
                     if k not in DELIBERATELY_UNRENDERED and k not in ui)
    assert not missing, (
        f"overview sends {missing} but the surface never mentions them — "
        "render them, or add them to DELIBERATELY_UNRENDERED with a reason")


def test_every_endpoint_the_server_exposes_is_called_by_the_surface():
    """Four endpoints were reachable only by curl, two of them since Slice 5."""
    ui = _ui_text()
    uncalled = sorted(e for e in _server_endpoints() if e not in ui)
    assert not uncalled, (
        f"the server exposes {uncalled} and nothing calls them — wire them up "
        "or delete them; a dead endpoint is a promise the product isn't keeping")


def test_the_built_surface_ships_with_the_repo():
    """The build output is committed so that cloning and running the server gives
    a working page with no Node and no network (X1: the toolchain is a
    contributor's concern, never a user's)."""
    static = WEB / "static"
    assert (static / "index.html").is_file(), "run `npm run build` in web/ui"
    assert (static / "app.js").is_file()


def test_the_surface_fetches_nothing_from_the_network():
    """Local-first breaks the moment the page needs a CDN. The built bundle must
    reference no external origin."""
    built = (WEB / "static" / "index.html").read_text() + \
            (WEB / "static" / "app.js").read_text()
    for origin in ("http://", "https://"):
        for hit in re.findall(rf'{origin}[^\s"\'`)]+', built):
            # Source-map and license comments naming a project URL are fine; a
            # fetched asset is not.
            assert not hit.startswith(("http://cdn", "https://cdn",
                                       "https://unpkg", "https://esm")), hit
