# Comment/docstring conversion — the spec

You are rewriting the prose in Python files. **Do not change a single line of
executable code.** Only comments, docstrings, and blank lines between them.

## The rule

A comment describes **what the code does**. It does not argue for why that
approach was chosen over another, does not narrate the history of the file, and
does not tell a story about a bug.

Rewrite this:

```python
def _strong_hint(proj, src, dst, distinctive=None) -> bool:
    """True when the descriptions NAME one of these two accounts distinctively.

    The evidence that separates 'payment to my card' (a transfer) from 'payment
    to my mortgage' (a real external outflow) is that the line carries something
    identifying the account it paid: its last four, its institution, a product
    word — and that nothing else you own carries the same thing.

    It used to also accept the bare word "card", which on a card statement is
    every line. That is why this is now the only path."""
```

into this:

```python
def _strong_hint(proj, src, dst, distinctive=None) -> bool:
    """True when either description carries a token distinctive to either account.

    `distinctive` is the map from `_distinctive`; it is recomputed if omitted."""
```

## What a docstring keeps

- What it does, in one line, imperative or declarative.
- Arguments whose meaning is not obvious from the name.
- What it returns, including the shape of a returned tuple or dict.
- What it raises, or that it never raises.
- Any invariant a caller must know to use it correctly (e.g. "idempotent",
  "returns empty rather than raising", "does not depend on iteration order").

## What comes out

- Dates, incident narratives, "this used to…", "the first live run…".
- Arguments for the design over an alternative.
- Numbers from a real vault, percentages, counts of what a run produced.
- Emphatic capitals, rhetorical questions, second person addressed to the reader.
- Anything that would read as an essay rather than a description.

## There is no exception. Tests are the guard.

Do NOT leave constraint comments, tombstones, or "do not reintroduce" notes.
If a rule must not be undone, the thing that stops it being undone is a **named
test**, not a comment asking politely.

`test_a_generic_word_no_longer_auto_links_anything` is worth more than any
paragraph, because it fails.

**So: if you are deleting a claim that is load-bearing and NOT covered by a test,
write the test.** Name it after the property. Then delete the prose. If you
cannot write the test, say so in HARVEST.md rather than keeping the comment.

## HARVEST.md is for what you could not turn into a test

Append an entry only when a deleted claim is load-bearing, is not in docs/, and
you could not write a test for it. Say why the test was not possible. Do not
harvest general design commentary — that is what is being removed.

Do NOT harvest reasoning that is already covered by:
- `docs/transfer-links-and-cross-document-corroboration.md` (the transfer matcher)
- `docs/the-maintenance-agent.md` (the agent runner, budgets, stakes)
- `docs/where-the-intelligence-goes.md` (raw-text classifiers and why they go)
- `docs/prompts-as-files.md` (prompt versioning)
- `docs/design-invariants.md` (T1–T9, X2, X3, I1, I5)

## Module docstrings

Keep them. A module docstring says what the module is for and how it fits with
its neighbours — that is description, not argument. Cut it to that.

## Tests

Test names and docstrings follow the same rule: say what the test asserts. A
test docstring that explains why the bug happened becomes one that states the
property being protected.

## Non-negotiable

- Executable code is byte-identical. Verify with `ast.dump` before and after if
  you are unsure.
- The full suite passes when you are done. Run it and report the count.
- Never introduce a real institution name, account number, merchant name, or
  street address. If you find one in a comment or test fixture, replace it with a
  synthetic value and note it in `HARVEST.md` under a `LEAK` heading.
