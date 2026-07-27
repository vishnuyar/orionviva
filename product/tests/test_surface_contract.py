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
UI_SRC = WEB / "static"


def _ui_text() -> str:
    if not UI_SRC.is_dir():
        pytest.skip("surface not present")
    # Slice 6.9: the surface is plain JS + HTML in `static/`, with NO build step.
    # The source and the served artifact are the same file, so this test now
    # checks the thing that actually runs rather than a source that is compiled
    # into it — which is the entire reason the build was removed.
    return "\n".join(p.read_text() for p in
                      list(UI_SRC.glob("*.js")) + list(UI_SRC.glob("*.html")))


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


def test_every_question_action_the_queue_emits_has_a_surface_handler():
    """The contract that actually drifted (found 2026-07-27): the queue offered
    "A new account" (action=confirm_identity) for the held Imprint statements,
    and app.js had no branch for it — the click did nothing, silently, and the
    question was unanswerable from the surface. The endpoint test above cannot
    catch this: `/api/confirm-identity` appears in the api table whether or not
    any button reaches it. What must stay in step is ACTIONS → HANDLERS."""
    q_src = (pathlib.Path(__file__).resolve().parents[1] /
             "viva" / "questions.py").read_text()
    actions = set(re.findall(r'"action":\s*"([a-z_]+)"', q_src))
    assert actions, "found no actions in questions.py — the regex has rotted"
    handled = set(re.findall(r"opt\.action === '([a-z_]+)'", _ui_text()))
    missing = sorted(actions - handled)
    assert not missing, (
        f"the question queue emits {missing} and the surface has no branch for "
        "them — the button would do nothing, silently. Wire it, or name it in "
        "a branch that says honestly that no flow exists yet")


def test_the_built_surface_ships_with_the_repo():
    """Cloning and running the server gives a working page with no Node, no
    network and no build (X1). Slice 6.9 went further: there is no toolchain at
    all, so the file a contributor reads IS the file the browser runs — the
    surface can no longer be silently stale."""
    static = WEB / "static"
    assert (static / "index.html").is_file()
    assert (static / "app.js").is_file()
    assert not (WEB / "ui").exists(), (
        "the build step was removed deliberately; do not reintroduce one "
        "without answering docs/the-surface-cards.md")
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


def test_the_three_natures_are_gone_from_the_surface():
    """Slice 9a replaced spending/transfer/settlement with the four majors, but
    the old three-button path stayed wired for a month: `Detail.jsx` called
    `api.ruleNature(...)` and `/api/rule-nature` answered it.

    Live code contradicting the current design is worse than no code, and this
    particular contradiction was already known to be wrong — "settlement" meant
    debt repayment while its button read *"Something I now own"*, which is an
    asset. A person answering honestly recorded the opposite of what they meant.

    The vocabulary is checked, not just the function name, so reintroducing the
    three natures under a new name still fails."""
    ui, server = _ui_text(), (WEB / "server.py").read_text()
    assert "ruleNature" not in ui
    assert "/api/rule-nature" not in server
    assert "/api/rule-nature" not in ui
    # Single quotes only: this codebase writes JS string literals that way, so
    # `'settlement'` is a value being passed while "settlement" in a comment is
    # the build log explaining why it left. Checking both would forbid the
    # explanation along with the mistake.
    assert "'settlement'" not in ui, "the old three-nature vocabulary is back"


def test_an_answer_carries_the_scope_the_question_chose():
    """The queue decides scope — a cheque is answered one at a time, a merchant
    once for all — and the surface must not re-decide it. It did: every option
    was posted as `{merchant, major, descriptor}`, so a movement-scoped question
    sent an undefined merchant and lost its `movement_key` entirely.

    The fix is that the button forwards the option's `args` wholesale."""
    ui = _ui_text()
    assert "api.ruleMajor(" in ui
    assert "...opt.args" in ui or "...o.args" in ui, \
        "an option's args must be forwarded WHOLE, not unpacked field by field"
    server = (WEB / "server.py").read_text()
    for field in ("movement_key", "group"):
        assert field in server, f"/api/rule-major must accept {field}"


def test_one_card_failing_does_not_take_the_page_down():
    """A wrong assumption about the shape of `undecomposed` replaced the ENTIRE
    surface with "I can't reach the ledger" — which was also false: the ledger
    had answered perfectly and every other card had its data in hand. A whole
    page lost, and a misleading reason given for losing it, from one bad guess
    about a field.

    So each card is drawn inside `safely()`: it fails narrowly, says what
    failed, and the rest of the page keeps working. Same rule as everywhere else
    here — degrade where it helps the person, and never mis-state the cause."""
    ui = _ui_text()
    assert "function safely(" in ui
    assert ui.count("safely(") > 5, "every card must be drawn through it"
    assert "rendering fault, not a data one" in ui, \
        "a display bug must not be reported as a ledger problem"


def test_the_surface_never_assumes_a_payload_shape():
    """`ruled_accounts` is a list, `undecomposed` is a map, `holders` may be
    either. Guessing produced `(ov.undecomposed || []).map is not a function`.
    One helper accepts all three, so no renderer carries its own assumption
    about a shape it cannot see."""
    ui = _ui_text()
    assert "const asRows" in ui
    for field in ("positions", "ruled_accounts", "undecomposed",
                  "income_breakdown", "holders"):
        assert f"asRows(ov.{field})" in ui, \
            f"{field} is read without the shape-tolerant helper"
