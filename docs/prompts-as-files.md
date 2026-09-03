# Prompts as Files

**State:** built
**Rules:** VOICE-6, VOICE-1, VOICE-2, VOICE-3, VOICE-4, VOICE-5

## Rules

### VOICE-6 — a recorded version resolves to the text that produced the reading
**State:** enforced
**Code:** core/vivacore/promptstore.py:34 (`load`), product/viva/prompts/
**Test:** product/tests/test_prompt_library.py::test_every_version_the_code_can_emit_resolves, product/tests/test_prompt_library.py::test_the_other_packages_keep_their_prompts_in_files_too

1. Every version id the code can emit resolves to the exact bytes a model was sent.
2. A version id retained in circulation keeps resolving after it stops being in force.
3. Prompt files are plain `.txt`, one file per version, and the filename is the id.

### VOICE-1 — no model-facing text lives in code
**State:** enforced
**Code:** core/vivacore/promptstore.py:34 (`load`)
**Test:** product/tests/test_prompt_library.py::test_no_prompt_text_lives_in_code

1. A multi-line string literal of 200 characters or more, in any `.py` file in any package, fails the build where it matches one of the check's instruction markers.
2. The failure message names the file, the line, and the `promptstore` call that replaces it. The gate is a marker list, so a shorter prompt, or one worded outside that list, passes (product/tests/test_prompt_library.py:216-231).
3. The same discipline applies to `core/vivacore` and `merchant/merchantcore`, not only `product/viva`.

### VOICE-2 — a released version file is immutable
**State:** enforced
**Code:** core/vivacore/versions.py:182 (`audit`)
**Test:** product/tests/test_versions.py::test_editing_a_released_version_fails

1. Editing or deleting a file pinned in `released` fails the suite.
2. Changing a prompt means copying it to a new version id, never editing a released one.
3. A version file nobody pinned, a family pointing at nothing released, and a newer version sitting unpromoted with no recorded reason each fail the suite.

### VOICE-3 — a version is declared once, as data, beside the code it governs
**State:** enforced-with-exception
**Code:** product/viva/versions.json, core/vivacore/versions.py
**Test:** product/tests/test_versions.py::test_no_version_id_is_declared_as_a_literal_in_the_modules_that_use_one

1. One `versions.json` per installable package holds `released` and `in_force`, with `withdrawn` nested inside a family's entry (core/vivacore/versions.py:218); nothing else declares a version id. product/viva/versions.json has no top-level `withdrawn` key.
2. A quoted version id reappearing in a module fails the suite.
3. `withdrawn` is keyed to a version, not to a family, so holding one version back leaves the next one raising the same complaint.
4. A family need not be a prompt: `merchantcore`'s `taxonomy` family pins `data/cat-v3.json`, and `TAXONOMY_VERSION` is read from the manifest.
5. Promotion is an explicit, reviewable act, never a consequence of a file appearing on disk.

**Exception:** `core/vivacore` has no manifest — `PROMPT_VERSION = "p2"` in core/vivacore/prompts.py and the `p2`/`t1`/`ti1` map are literals, and those prompt files are pinned nowhere.

### VOICE-4 — a missing version raises rather than defaulting
**State:** enforced
**Code:** core/vivacore/promptstore.py:23 (`PromptNotFound`), :40
**Test:** product/tests/test_prompt_library.py::test_a_missing_version_raises_rather_than_defaulting

1. Resolving an unknown version id raises.
2. No lookup falls back to the version currently in force.

### VOICE-5 — a version file may hold a keyed table, and its tags are an interface
**State:** enforced
**Code:** product/viva/prompts/semantic-request-retry-v7.txt
**Test:** product/tests/test_answer_program_contracts.py::test_compiler_repairs_a_malformed_semantic_request_before_any_read

1. The repair prompt receives every compact-contract defect and asks for one complete replacement semantic request.
2. Repair happens before any financial read and the model never sees partial results.
3. Changing the repair contract creates a new prompt version.
4. Version 3 kept grounded user wording for entities while restricting
   clarification tags to the reviewed ambiguity vocabulary. Version 4 adds a
   bounded user-specific entity catalog and locally verifies catalog selection.
   Version 5 collapses labels with the same deterministic answer effect and
   records a sanitized failure code when a response needs repair. Version 6
   separates catalog ids from unresolved grounded phrases in the model-facing
   schema and makes transparent entity interpretation part of delivery.
   Version 7 makes the representation decision meaning-first in both the
   prompt and native tool schema: a uniquely fitting catalog entry wins even
   when an indirect description shares no words with its label.

## Why

Intent loses to friction. Adding a prompt as a Python literal was one line and
adding it to a library was five plus an import, so the library lost every time
regardless of what anyone meant to do. The fix has two halves and the second is
the load-bearing one: make the data path cheaper than the code path, and make
the code path fail a test. Saying it again was already tried and it drifted
twice.

The reason a version id must resolve forever is that stamping a version is the
whole mechanism by which a stored read can be re-derived and re-explained. A
version id that resolves to nothing is decoration. That was not hypothetical:
`merchantcore` held a single `_PROMPT` string edited in place while
`ENRICHMENT_VERSION` was bumped, so events named text that was not in the
codebase. Git history holds the bytes, but *"go read git history"* is exactly
the archaeology the library exists to abolish. An admitted gap is a different
thing from an unnoticed one, which is why an unrecoverable version is recorded
in the file rather than left as a silent hole.

The migration proved itself: the pre-existing frozen-digest test passed with its
pinned digests untouched, so nothing needed eyeballing — one changed byte would
have failed it. The lint then caught three prompts on its first run that no
audit had flagged, including the benchmark's input-mode headers. A benchmark
that can reword its own question between runs measures nothing. That is the
argument for mechanism over vigilance in one line, and it is why the rule has no
exceptions: no model-facing text in a `.py` file, delimiters included.

The declaration was a separate problem one level up. Resolving the highest
version at run time fails mechanically four ways — `sorted()` is lexicographic
so `v10` reverts to `v2`; a family notion has to be invented anyway because
`speak-v6` and `speak-refusal-schema-v1` share a directory; a version
deliberately held back is unexpressible; and a composite id has two axes with no
"highest". But none of those decided it. Auto-resolution puts a new prompt in
force the moment a file lands with no diff showing that behaviour changed — the
same stale-artifact failure a build step was reversed over. The declaration is
the review gate. The problem was that it was made in eighteen places. What the
lint removes is not the decision; it is the ability to forget you owed one.

That example has dated itself, and the way it dated is the argument. `speak-v6`
was the id in force when the paragraph above was written; the family in force
today is `speak-v12`. So the first of those four failures is no longer
hypothetical here — `speak-v12` sorts *below* `speak-v6`, and a build that
resolved the highest version at run time would today put a six-promotion-old
prompt in force and record it as current.

Manifests are per package, not per repo, because the three ship as
independently installable wheels. Package-data configuration matters for the
same reason a packaging slip does: invisible in a checkout, fatal in an install.

A prompt file must be readable and editable by someone who does not know
Python, because eventually that person is the user tuning their own agent. User
overrides are designed for and deferred: an edited prompt breaks the digest
chain, so a stored read would resolve to text the user changed. Overrides must
arrive as content-addressed new versions rather than edits — a slice, not a
config flag. The loader takes a directory argument precisely so that stays a
second search path rather than a rewrite.

A version is released by being pinned in the manifest, not by a commit reaching
a remote. VOICE-6's subject is the recorded stamp, and a stamp does not know which
branch it was written on. So once a version is in the manifest the next phrasing
change is a new id, even while the commit that released the last one is still
local, and even if nobody but you has ever run it.

A version id also answers a question it was not designed for: because it is
self-describing and permanent, it identifies what *type* of document a stored
read was, for a family whose extraction JSON does not name its own type.
Recovery matches the version's *family* rather than the exact string — matching
exactly fails on any document read under an earlier version of a profile that
has since been bumped.

## Open

- `core/vivacore` has no manifest, and its five prompt files are pinned nowhere. `t1` and `ti1` do not name single files, so a manifest cannot key them until that is settled.
- Event stamps carry a bare id: `QuestionDeclined` records `pack-v3`, not `pack-v3@62a56a4b`. `versions.stamp()` exists and is tested, but changing it changes recorded payloads, so it is its own cycle.
- The literal test is textual. An id built by concatenation or an f-string passes it and is caught nowhere.
- `FROZEN_SPEAK_PROMPTS` is the one frozen map still kept by hand; it is one comprehension away from deriving from `released` like the other four.
- User-editable prompts, as content-addressed new versions rather than edits.
