# Prompts as Files

**Status:** ✅ **BUILT 2026-07-25** — P1 = (a), read-only package data · **Created:** 2026-07-25 · **Origin:** Vishnu: *"move all the prompts and versions out of code — I had mentioned this previously, it still drifted. Prompt versions have gone up but the previous versions are buried in code."*

**Invariants touched:** **T8 (a recorded `prompt_version` must resolve to the exact text that produced it)** · T3 (raw capture is worthless if the instructions behind it are unrecoverable) · I5 (code universal, specifics are data — a prompt is the most specific data there is) · X1 (a contributor's toolchain is never a user's problem).

---

## The state, counted

**18 prompt versions live in four different places**, under three different disciplines:

| Where | Versions | Retention |
|---|---|---|
| `product/viva/ingest/prompt_library.py` (424 lines) | 14 | ✅ append-only, **frozen-hash test** |
| `merchant/merchantcore/enrich.py` — `_PROMPT` | 1 text, version bumped **v1 → v2 → v3** | ❌ **none** |
| `core/vivacore/prompts.py` — `EXTRACTION_PROMPT` | 1 text, `PROMPT_VERSION = "p2"` | ❌ none |
| `product/viva/listen.py` — until this session | 1 | ❌ none (now migrated) |

### The finding that matters

**`enrich-v1` and `enrich-v2` no longer exist.** `merchantcore` holds a *single* `_PROMPT` string that has been **edited in place** three times while `ENRICHMENT_VERSION` was bumped. Every `MerchantEnriched` event recorded under `enrich-v1` or `enrich-v2` names a prompt version whose text is **not in the codebase**. `vivacore.prompts` has the same shape: `PROMPT_VERSION = "p2"` with no `p1` anywhere.

That is a **T8 violation already in the vault**, not a hypothetical. The whole point of stamping a version is that a stored read can be re-derived and re-explained; a version id that resolves to nothing is decoration.

It is recoverable — `git log -p` on those three commits has the exact bytes — but *"go read git history"* is precisely the archaeology the prompt library was built to abolish.

## Why it drifted, twice

Because **the library is Python.** Adding a prompt means editing a module, importing it, wiring a dict. When you are inside `listen.py` building a feature, a local `"""..."""` is one line and the library is five plus an import. The path of least resistance wins, every time, regardless of intent — which is why saying it again would not work either.

So the fix has two parts, and the second is the one that matters:

1. **Make the data path easier than the code path.** Adding a prompt should be *creating a file*, with no Python to edit at all.
2. **Make the code path fail a test.** A prompt-shaped string literal in a `.py` file becomes a build failure, not a code-review hope.

---

# The plan

Six steps, ordered by reversibility. **Nothing changes any prompt's text** — this is a move, and the existing frozen-hash test is what proves it.

### Step 1 — The loader (`vivacore.promptstore`)

One small module, shared by all three packages. `merchantcore` must not depend on the product (T9 cuts both ways), and `vivacore` is already the common floor.

```
load(package_dir, "classify-v2")  -> str      # exact bytes, no interpolation
ids(package_dir)                  -> [str]    # what exists
digest(package_dir, version)      -> str      # sha256[:16]
```

Files sit beside the code that uses them, one per version, **filename is the id**:

```
core/vivacore/prompts/              extract-image-p2.txt
product/viva/prompts/               classify-v1.txt  classify-v2.txt
                                    extract-base-v1.txt  extract-card-v1.txt … 
                                    interpret-v1.txt  interpret-v2.txt
merchant/merchantcore/prompts/      enrich-v3.txt  (+ v1, v2 recovered)
```

Plain `.txt`. No YAML, no front-matter, no templating engine — placeholders stay Python `str.format` fields, which is what every call site already uses. **A prompt file must be readable and editable by someone who does not know Python**, because eventually that person is the user tuning their own agent.

Read via `importlib.resources` so it works from a wheel, a zip, or a checkout, and add package-data config so the files actually ship (X1: the packaging is our problem, never the user's).

### Step 2 — Migrate, and let the old test prove it

Move all 14 `prompt_library.py` versions to files **byte for byte**. Then:

> **The existing `test_active_versions_are_frozen` must pass unchanged, with its pinned digests untouched.**

That is the whole verification. The test that has been enforcing retention becomes the proof that the migration altered nothing — no new test to trust, no diff to eyeball. If a single character moved, a digest changes and it fails.

`prompt_library.py` shrinks from 424 lines to a thin accessor keeping its current API (`classify_prompt`, `compose_extraction`, `interpret_prompt`, `resolve`), so **no call site changes in this step.**

### Step 3 — Recover the lost versions

`git log -p merchant/merchantcore/enrich.py` across its three commits yields the exact `enrich-v1` and `enrich-v2` text. Write them out as files, pin their digests, and `resolve("enrich-v1")` works again — which means every `MerchantEnriched` event already in the vault becomes explainable again.

Same for `vivacore`'s `p1` if it exists in history; if it genuinely predates version control, record that honestly in the file (`# text not recovered — this vault has reads that cannot be re-derived`) rather than leaving a silent hole. **An admitted gap is a different thing from an unnoticed one.**

### Step 4 — Bring the two unversioned prompts under the discipline

`merchantcore._PROMPT` and `vivacore.EXTRACTION_PROMPT` become library entries with real ids. Both packages get the frozen-hash test the product already has — the discipline stops being one module's local habit and becomes the project's.

### Step 5 — The test that makes it stick

`test_no_prompts_in_code`: walk every `.py` in the repo, parse it with `ast`, and fail on any string literal that is **long (>200 chars), multi-line, and instruction-shaped**. The one legitimate home for such a string is a `prompts/` file.

Two honest notes about this test:

- **It is itself a keyword check**, and I have just spent a session deleting those ([[practice-no-substring-lists-for-ambiguity]]). The distinction is real and worth stating: that lesson is about **classifying a user's data**, where being wrong corrupts a ledger. This is a **lint over our own source**, where being wrong costs a contributor an `# allow-prompt` comment. Different blast radius, different rule.
- It must be **cheap to satisfy**: the failure message should name the file, the line, and the exact `promptstore` call to replace it with. A test that only says "no" trains people to add exemptions.

Plus `test_every_recorded_version_resolves`: for every version id the code can *emit*, `resolve()` returns text. That is T8 asserted directly, and it is the test whose absence let `enrich-v1` disappear.

### Step 6 — Make adding one obvious

A three-line `product/viva/prompts/README.md`: *to change a prompt, copy the file to a new id, edit, point the profile at it, add the digest.* Plus a line in `CLAUDE.md` under the standing practices, so it is loaded in every session rather than remembered.

---

## Decision for Vishnu

**P1 — do prompt files ship as read-only package data, or as a user-editable directory?**

- **(a) package data, read-only** — simple, versioned with the code, digests always match. My lean for now.
- **(b) package data + an optional user override directory** — a person could tune their own agent's prompts, which is very much in this project's spirit (your keys, your machine, your rules) — but an edited prompt breaks the digest chain, so a stored read would resolve to text the user changed. That is a **T8 hazard wearing a feature's clothes**: it would need overrides to be *content-addressed as new versions* rather than edits, which is a slice, not a config flag.

**My lean: (a) now, (b) designed for and deferred.** The loader takes a directory argument precisely so (b) is later a second search path rather than a rewrite.

## What this does not do

No prompt text changes. No event schema change. No re-ingest. No call-site changes in Steps 1–3. If the whole thing were reverted, the only loss would be the recovered `enrich-v1`/`v2` files, which are pure gain.

## Cost

Roughly: Step 1 ~60 lines, Step 2 mechanical (a script does the extraction, the frozen test judges it), Steps 3–4 an hour, Step 5 ~40 lines plus the exemption plumbing, Step 6 minutes. The expensive part is already done — **the discipline exists in `prompt_library.py`; this makes it structural and universal instead of local and voluntary.**

---

## What the build showed

**20 prompt versions now live in files**, across three packages, and **no prompt text remains in any `.py` file** in the repo.

| Package | Directory | Versions |
|---|---|---|
| `product/viva` | `prompts/` | 15 — classify ×2, extract base ×4, fragments ×7, interpret ×2 |
| `core/vivacore` | `prompts/` | 5 — the p2 body, three mode headers, the page-text block |
| `merchant/merchantcore` | `prompts/` | 2 — `enrich-v2` (recovered), `enrich-v3` |

**The migration proved itself, exactly as planned.** `test_active_versions_are_frozen` passes with its **pinned digests untouched** — the same numbers it had when the text lived in Python. Nothing to eyeball; one changed byte would have failed it. `prompt_library.py` went from **424 lines to 88**, and holds no prompt text at all.

### Three things the build turned up

**`enrich-v1` never existed.** The plan assumed two lost versions; git shows `merchantcore` shipped at `enrich-v2` and the constant simply started there. So `enrich-v2` was recovered and **nothing is actually unexplainable** — a better outcome than expected, and worth stating plainly rather than letting the plan's guess stand as history.

**The lint caught three more prompts on its very first run** — `_HEADERS` in `vivacore/prompts.py`, holding the three input-mode openings for the benchmark. Nobody had flagged them; they were not in the plan's inventory. A benchmark that could reword its own question between runs would measure nothing, so those are now pinned files too. **The test found drift the audit had missed on its first execution**, which is the argument for mechanism over vigilance in one line.

**`_PAGE_TEXT_BLOCK` moved too**, though it is a delimiter rather than an instruction. The rule is easier to keep when it has no exceptions: *no model-facing text in a `.py` file*, full stop.

### The guarantee, stated plainly

- **`test_no_prompt_text_lives_in_code`** — an AST walk over every `.py` in all four packages, failing on long multi-line instruction-shaped literals, with the fix printed in the message.
- **`test_every_version_the_code_can_emit_resolves`** — T8 asserted directly. This is the test whose absence let `enrich-v2` slip out of the codebase while events kept naming it.
- **`PromptNotFound`** raises rather than defaulting. A silent fallback to the *current* prompt would re-explain an old reading with new instructions and look like it worked — the most dangerous possible failure for a system whose product is trust.
- **`package-data` in all three `pyproject.toml`s.** A packaging slip is invisible in a checkout and fatal in an install (X1).

### A recorded version resolves to a family, not only to itself

Because a version id is self-describing and permanent, it can answer a question it was never designed for: what *type* of document a stored read was. The balance family's extraction JSON does not name its own type, so replaying from stored claims has only the recorded `prompt_version` to go on — and that turns out to be enough, provided recovery matches the version's *family* rather than the exact string. Matching exactly fails on any document read under an earlier version of a profile that has since been bumped: the type was written down, and we were asking for an exact match on the one part designed to change.

### Retained versions in circulation

Every version below still resolves; records written under any of them keep their meaning.

- `enrich-v2` — the sixteen controlled primaries plus a model-supplied subcategory.
- `enrich-v3` — adds `counterparty_kind` and the implication block.
- `enrich-v4` — shows the model the subcategories this vault already uses, so minting a new label is a deliberate act rather than the path of least resistance.

### Deferred, deliberately

User-editable prompts (P1 (b)). `promptstore.load()` takes a directory argument precisely so an override path is later a second lookup rather than a rewrite — but an edited prompt breaks the digest chain, so overrides must arrive as **content-addressed new versions**, not edits. That is a slice, not a config flag.
