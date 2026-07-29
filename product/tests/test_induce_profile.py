"""The induction surface: which lines get grouped, and where grammars live.

The model call itself is merchantcore's and is tested there. What belongs to the
product is the part that decides WHAT is shown to it — a grammar is per
(institution x kind), and mixing two banks' lines into one sample would induce a
grammar that is neither bank's.
"""

import os
import types

from viva.induce_profile import _pairs, profiles_dir


class _Proj:
    """A projection stub: two banks, three kinds, one blank descriptor."""

    def __init__(self, rows):
        self._rows = rows
        self._acct = {"a": ("Northbank", "depository"),
                      "b": ("Northbank", "liability"),
                      "c": ("Meridian", "liability")}

    def movements(self):
        # Dates are ISO strings, as MovementInfo carries them — `_pairs` slices a
        # recent window and would otherwise be reading a type the ledger never
        # emits, which is how the last two defects in this module got in.
        return [types.SimpleNamespace(account=a, description=d,
                                      date=f"2026-01-{i + 1:02d}")
                for i, (a, d) in enumerate(self._rows)]

    def account_info(self, account):
        if account not in self._acct:
            raise KeyError(account)
        inst, kind = self._acct[account]
        return types.SimpleNamespace(institution=inst, kind=kind)


def test_lines_are_grouped_by_institution_and_kind_not_by_institution():
    pairs, _recent = _pairs(_Proj([("a", "ZELLE TO JOHN SMITH"), ("a", "ZELLE TO JOHN SMITH"),
                          ("b", "CARD PURCHASE 03/14 SHOP"),
                          ("c", "CARD PURCHASE 03/14 SHOP")]))
    # One bank's checking and card lines are unrelated languages, so they are
    # never sampled together — and the same line shape at two banks is two
    # grammars, because only one of them is known to have composed it that way.
    assert set(pairs) == {("Northbank", "depository"), ("Northbank", "liability"),
                          ("Meridian", "liability")}
    assert pairs[("Northbank", "depository")] == {"ZELLE TO JOHN SMITH": 2}


def test_a_movement_with_no_descriptor_or_no_account_is_skipped_not_guessed():
    pairs, _recent = _pairs(_Proj([("a", "  "), ("a", None), ("zz", "ORPHAN LINE"),
                          ("a", "REAL LINE")]))
    assert pairs == {("Northbank", "depository"): {"REAL LINE": 1}}


def test_grammars_live_in_merchantcore_not_in_the_vault_or_the_product(
        monkeypatch, tmp_path):
    """A bank's line grammar is the bank's, identical for every customer, and it
    outlives any ledger. It used to sit under the product's home directory,
    which quietly said it belonged to the product.

    It lives outside the working tree deliberately: what an installation induces
    can carry a person's name baked into a template literal, and keeping it
    where git cannot see it makes that impossible to commit rather than merely
    inadvisable. The package's SHIPPED seed is a separate directory, committed,
    and nothing moves into it without a person deciding."""
    monkeypatch.delenv("VIVA_PROFILES", raising=False)
    monkeypatch.delenv("MERCHANTCORE_HOME", raising=False)
    assert str(profiles_dir()) == os.path.expanduser("~/.merchantcore/profiles")

    monkeypatch.setenv("MERCHANTCORE_HOME", str(tmp_path))
    assert profiles_dir() == tmp_path / "profiles"

    # Learned and shipped are never the same place, or a `git add` could commit
    # a grammar nobody read.
    from merchantcore import home
    assert home.shipped_profiles_dir() != profiles_dir()
    assert "site-packages" in str(home.shipped()) or \
        "merchantcore" in str(home.shipped())
