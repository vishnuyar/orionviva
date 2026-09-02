# Prompts

**One file per version. The filename is the version id. Nothing here is code.**

To change a prompt:

1. **Copy** the file to a new id — `card-v1.txt` → `card-v2.txt`. Never edit a
   released one.
2. **Edit** the copy.
3. **Point** the family at it — the `in_force` entry in `viva/versions.json`,
   which is what `vivacore.versions.active` reads.
4. **Pin** the new digest under `released` in `viva/versions.json`. Most frozen
   tables in `tests/` derive from that map; `FROZEN_SPEAK_PROMPTS` in
   The manifest is the single digest authority for released speak prompts.

Step 1 is the whole discipline. A reading recorded under `card-v1` must resolve
to card-v1's text forever (T8) — that is what makes a stored answer explainable
a year later, and what a frozen digest enforces.

`enrich-v2`'s text was lost this way once: a single literal edited in place while
its version constant was bumped. It was recovered from git history on
2026-07-25; the next one might not be.

## Two shapes of file

**One prompt.** The whole text is sent. Placeholders are ordinary Python
`str.format` fields — `{said}`, `{page_number}`. Literal braces in example JSON
must be doubled: `{{"legs": []}}`.

**A keyed table.** One `tag: words` line per entry, split on the first colon;
a line with no colon, or with nothing after it, is ignored. `speak-repairs-v1.txt`
is the first of these: one line per repair a malformed reply can be asked to
make, chosen by the tag the check that found the defect named, and inserted
into another prompt's placeholder. A table's own text is never `.format`ed, so
braces in it are literal.

Versioning is identical for both, and a table carries one extra obligation: its
set of tags is an interface. Adding, removing or renaming a tag is a new
version file, because the code that names a tag and the file that answers it
must agree — `test_every_repair_a_check_can_name_has_reviewed_words` fails when
they do not.

The runtime answer boundary uses `semantic-request-*.txt`. These prompts teach
only the compact reviewed family catalog, typed request schema, and exact
question/prior-turn provenance required for every semantic parameter. Executable
AnswerProgram and financial-query prompts remain released historical artifacts,
but are not loaded by the runtime semantic compiler.
