# Public prepared-sample build identity

**State:** portable public build proof implemented with supporting tests; complete artifact and frozen restoration pending
**Rules:** none

The prepared sample must contain synthetic financial sources and portable build proof without publishing developer filesystem paths. Independent inspection in `runs/incremental-import/packaged-harness-factcheck/report.md` found `sample.snapshot.export` copies the entire private runtime identity into public `snapshot.json`. That includes absolute package roots and interpreter path. The public field is required as a metadata key but its value is not used for restore, code compatibility, canonical authentication or source closure. The full private readiness receipt, in contrast, is checked by reopen and activation and must remain unchanged.

Approve a narrow change to `product/viva/sample/snapshot.py` and its snapshot tests: export a portable public identity containing the existing package-files SHA256, file count, Python version and executable SHA256, together with a SHA256 of the exact full private runtime identity. Publish no roots or executable pathname. Retain the complete original receipt and its exact runtime comparisons in the ignored private build instance. Do not rewrite existing receipts, relax runtime compatibility or remove any artifact/source/event check. The builder will naturally generate and pin the new snapshot metadata only after the complete production build; the artifact is currently unbuilt.

Acceptance: prove the public representation has only the declared portable fields, carries the original hashes/count/version, contains no synthetic absolute fixture paths, and binds changes to the full private identity by digest. Verify the input receipt remains untouched. Existing snapshot/restore/worker tests must pass and independent review must inspect this exact small diff. Full artifact and frozen restoration remain separate pending gates. No financial meaning, credentials, provider work, private-vault access, commit, installation or release change belongs here.

Retaining full paths in the public artifact is rejected because they add no runtime validation; dropping build proof altogether is rejected because it weakens reproducibility. No product edit is authorized until the Director ruling is recorded.

## Director ruling — Checkpoint 1

The Director approved this public prepared-sample build-metadata privacy correction after reviewing the proposal, independent finding and export code. Scope is limited to `sample/snapshot.py` and focused snapshot tests. Export only the declared package-files hash, file count, Python version, executable hash and SHA256 of deterministically encoded complete private runtime identity. Publish no roots or executable pathname. Preserve the full private receipt, exact comparisons and every authentication, compatibility, event and source-closure check.

Acceptance must prove the closed public field set, retained values, digest sensitivity anywhere in the private identity, absence of synthetic absolute fixture paths and unchanged input receipt. Existing snapshot/restore/worker checks and fresh independent review remain required. Generate and pin final metadata only from the complete validated build. No full-artifact/restoration pass, financial change, provider work, private-vault access, commit, installation replacement, release, push or merge is authorized. Persisted by the parent in the Director's name; the Director remained read-only.
