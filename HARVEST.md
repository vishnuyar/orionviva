
## LEAK — 2026-08-12

Three real identifiers used as test fixtures in `merchant/tests/test_profile.py`:
a contact phone number that belongs to the other party on a peer-payment line, a
second contact phone number carried on a card line, and a routing number with the
reference beside it from a wire descriptor. Each was copied out of a real
descriptor while the names around it were being synthesised — the brand was
replaced, the digits attached to it were not. All of them are already published.
Replaced with numbers in the reserved fictional `555-01xx` range and with a
routing number that carries a valid checksum under a prefix no institution is
assigned, so the shapes the tests were written to exercise still hold.

The denylist could not have caught any of them. `.denylist` holds names — holder
and institution names, matched as lowercase substrings — and a phone number, a
routing number and a wire reference are not names, so there is no entry that
would ever match them. What caught them is comparing the tracked tree against
the real-run artifact corpus token by token, which needs no vocabulary at all.
The same comparison also proved the replacements: a synthetic value that collided
with a real one would be the same leak with a longer story.

Two things the comparison taught about doing it. A digit-run grep cannot see a
hyphenated phone number, so the run has to normalise separators away on both
sides. And most of the corpus quotes the repo back at itself, so matching against
all of it buries the signal; the corpus has to be narrowed to the files that are
genuinely vault-derived before anything is judged.

## LEAK — 2026-08-09

A real card product name and a real masked account fragment, copied out of a
live `viva.speak` run into an amendment in
`docs/projection-decomposition-and-the-tool-registry.md`. Replaced with the
synthetic account the test fixtures already use (`Everyday Checking ••••4417`).

It was not caught by the denylist: neither the product name nor the fragment is
an entry, and `.denylist` holds holder and institution names rather than card
product names or the opaque tails that appear in a masked identifier. The
pattern grep is what caught it, on the second attempt — the first ran against
an empty file list and reported clean, which is the more useful finding of the
two. A paranoia grep that cannot fail loudly is worse than none, so the file
list is now built to disk and its length printed before anything is judged.
