
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
