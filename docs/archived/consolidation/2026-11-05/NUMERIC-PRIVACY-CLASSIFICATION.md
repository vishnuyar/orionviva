# Exact candidate numeric/privacy classification

Reviewed the 68 paths pinned individually in `NUMERIC-PRIVACY-CLASSIFICATION.json`: 28 tracked modifications and 40 untracked public additions. Every path was readable UTF-8, regular source/document data, and hash-stable before and after review. No source, index, test or vault was changed or executed. Only the approved existing denylist scanner was executed; no model or provider calls occurred.

## Result

The existing `scripts/check_denylist.py` returned exit 0/clean against these exact 68 files using the original nonempty pattern source at `/Users/vishnu/orionviva/.denylist`. Its captured output was not published. No pattern or private value was printed. No skipped binary/lockfile existed in this exact candidate list.

Numeric patterns were reviewed separately, including contextual short account-like literals. No unresolved privacy hit was found within these declared shapes. Counts below are match occurrences, not unique values or files:

- Dollar amounts with cents: 0.
- Comma-grouped shapes: 11; all test/source counts, digit limits, documented coverage counts or Python argument separators falsely resembling grouped numbers.
- Long digit runs embedded in source/audit hashes: 3,972, including one concatenated audit-reference spelling whose hash context was manually checked.
- Synthetic fixture/boundary-control long digit runs: 68; generated account identifiers in synthetic Alpha/Beta/Gamma/Background scenarios, explicitly synthetic investment source fixtures, large Decimal cancellation/precision cases, signed-header rejection bounds and a Decimal freeze/thaw regression. Their constructing functions/data and synthetic context were checked; no value was classified merely because its filename starts with test.
- Hexadecimal alphabets/signed-header production bounds: 14.
- Recorded elapsed-time digit run: 1; a historical launcher timing receipt, not a financial amount.
- Account-schema or synthetic fixture contextual matches: 56. Production occurrences are field access/schema/identifier-prefix references; tests include synthetic physical-account forgeries, generated account numbers and a masked synthetic-number case. No retained account fragment was found.
- Quoted 4–8-digit short-literal secondary screen: 10,890. Of these, 10,858 are source-ledger Git-mode fields, eight are consolidation script Git-mode constants, and 24 are synthetic fixture account/balance values or invalid-date controls. All JSON mode fields were checked structurally; source/test contexts were checked without emitting values.

An initial intentionally broad context scan also matched Markdown emphasis, Python keyword unpacking and the word pending; these lexical false positives were narrowed to account-field/last-four/masked-literal patterns rather than reported as private financial hits. The safe working input replaces digits with placeholders and contains no numeric match values. The final JSON publishes only path, source hash, categories and counts.

## Scope and remaining gate

This closes the requested paranoia classification for the exact pinned 68-file candidate, not future documentation/test-result edits or an arbitrary staged tree. Root's later stale-status/docs corrections and any copied report must be separately scanned. After staging is independently authorized, verify the actual staged paths/blobs against the final reviewed allowlist. Keep hook output private because a hook may echo matched text; no hook bypass is authorized or needed by this report. The ignored TODO and private/runtime preservation evidence remain outside Git.

No acceptance, default migration, normal-route performance, full794, A/B test outcome or release claim follows. Existing source preservation and qualification records remain unchanged. No uncertainty required stopping this classification; the remaining limit is exact-byte scope, not a claim that regex scanning establishes all possible privacy properties.
