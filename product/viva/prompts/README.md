# Prompts

**One file per version. The filename is the version id. Nothing here is code.**

To change a prompt:

1. **Copy** the file to a new id — `card-v1.txt` → `card-v2.txt`. Never edit a
   released one.
2. **Edit** the copy.
3. **Point** the profile at it (`registry.py`) or the accessor's default
   (`prompt_library.py`).
4. **Pin** the new digest in `FROZEN` in `tests/test_prompt_library.py`.

Step 1 is the whole discipline. A reading recorded under `card-v1` must resolve
to card-v1's text forever (T8) — that is what makes a stored answer explainable
a year later, and what a frozen digest enforces.

`enrich-v2`'s text was lost this way once: a single literal edited in place while
its version constant was bumped. It was recovered from git history on
2026-07-25; the next one might not be.

Placeholders are ordinary Python `str.format` fields — `{said}`, `{page_number}`.
Literal braces in example JSON must be doubled: `{{"legs": []}}`.
