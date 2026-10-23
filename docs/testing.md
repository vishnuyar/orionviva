# Testing OrionViva

Use `.venv/bin/python scripts/test.py` from the repository root for feedback
while editing. It compares the working tree with `HEAD`, including staged,
unstaged and untracked files. `--base main` includes committed branch work.
Always compare against the branch you actually started from.

| Command | Scope |
| --- | --- |
| `.venv/bin/python scripts/test.py --dry-run` | Explain the current selection without executing it |
| `.venv/bin/python scripts/test.py --files desktop/src/app/selection.ts` | Tests related to an explicit changed path |
| `.venv/bin/python scripts/test.py --package product` | Complete product Python suite |
| `.venv/bin/python scripts/test.py --package desktop` | Complete shared UI suite |
| `.venv/bin/python scripts/test.py --all` | Complete Python and UI suites |

The package choices are `core`, `merchant`, `product`, `bench`, and `desktop`.
`--files` describes changed paths, rather than an exact list of tests to run.
For an exact test invocation, use pytest or Vitest directly.

## How affected selection works

Python source and test edits select tests through the transitive local import
graph, including relative imports, package initializers, test helpers, literal
dynamic imports and dotted monkeypatch targets. Nonliteral dynamic imports
conservatively depend on every local Python module. A source with no discovered
test dependents runs its complete package. Backend source edits also run the
complete UI suite because serialized contracts cross that boundary. Edits
confined to Python's `tests/` directories run only their affected Python tests;
they can be combined with related frontend tests when UI source also changes.

Frontend-only TypeScript edits use the installed Vitest `related --run`
dependency traversal. Resource edits, configuration, scripts, documentation,
unknown paths, deleted files, package initializers and shared test setup select
the complete Python and UI suites. No changes prints an explicit message and
runs nothing. Commands stop and return a failure as soon as a runner fails.

Static imports cannot prove every runtime dependency: reflection, source-file
inspection and paths assembled at runtime can evade the graph. Affected runs
provide local feedback. Use complete affected-package checks and `--all` at
the existing verification gates; CI continues to collect the complete Python
and shared UI suites. This command does not run architecture/style checks,
builds, Rust tests, browser-host smoke tests, packaged artifact validation, or
independent acceptance and hosted qualification. Those retain their existing
gates. Run the frontend's `npm run check:architecture`,
`npm run check:styles`, and `npm run build` when validating frontend work.

## Coverage ownership and test cost

Keep behavior assertions at the narrowest useful boundary. Unit tests own
combinatorial input validation; integration tests own composition and durable
state; shared UI tests own rendering and interaction; native tests own OS and
packaging behavior. Different assertions at these boundaries are useful even
when their names sound similar. Parameter rows for corruption modes, Unicode
byte limits, currencies, or privilege boundaries are distinct coverage.

The product's correction tests retain one copy of an identical group-correction
scenario. The startup scale tests build and audit each 1k/10k/50k encrypted log
once, then exercise warm open and independent missing/corrupt read-store copies.
The real encryption, authenticated head, corruption states, no-traversal
assertions and three-second open deadline remain exercised.

CI runs surface contract tests within the complete Python suite; the surface
job owns generated-contract and impact checks. Shared UI tests and frontend
architecture/style checks run once on Linux. Native storage, Rust tests,
sidecar execution, lifecycle checks and native builds still run on macOS,
Windows and Linux.

Measure before changing coverage. For Python, append `--durations=20` to a
direct pytest run. For the UI, use Vitest's JSON reporter to retain per-file
durations. Compare the same scenario set and machine before and after, including
fixture construction. Fewer test functions alone is not a runtime result.
