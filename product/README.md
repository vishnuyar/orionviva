# viva — the OrionViva product

The trust core of OrionViva: an **encrypted, append-only, double-entry ledger**
and the projections that answer questions about it honestly.

Two invariants hold from the first commit:

- **Events are the source of truth** (ADR-004). Everything the ledger knows is an
  append-only, hash-chained sequence of events. Balances and every other view are
  *projections*, rebuilt by replaying the log. The chain is tamper-evident and can
  be verified without the key.
- **Encrypted at rest** (ADR-005). Every event body is sealed with AES-256-GCM
  under a passphrase-derived key (scrypt), in a *versioned* envelope. The
  passphrase is never stored. What cannot be decrypted cannot be leaked.

No model sits in the v0 answer path. A balance is **arithmetic over attested
records**, and every answer carries a **grade** (`verified` / `corroborated` /
`unverified` / `conflicted`) and **provenance** (which document, page, region).

## Layout

- `viva/crypto.py` — the versioned AES-256-GCM + scrypt envelope.
- `viva/ledger/events.py` — the event vocabulary and the `Posting` shape.
- `viva/ledger/postings.py` — double-entry builders (single + amount-split).
- `viva/ledger/store.py` — the encrypted, hash-chained `EventStore`.
- `viva/ledger/projection.py` — `LedgerProjection.balance()` → figure + grade + source.
- `viva/answer.py` — the answer path: `answer_balance` / `answer_total` / `coverage_summary`, with honest refusal (no LLM).
- `viva/ingest/review.py` — held-statement review + human correction-as-event (posts at `verified`).
- `viva/vault.py` — a vault: one directory + passphrase holding the event log and raw blobs.
- `viva/web/` — the local surface: a stdlib HTTP server + a single self-contained page (dashboard, review/confirm, account drill-down, upload). Provenance built in, kept quiet.

## Development setup

Two packages, `vivacore` (in `../core`) and `viva` (here), that the product
imports. Pick **one** way to make them importable, and be consistent:

**Editable install (recommended for ongoing work).** From the repo root:

```
pip install -e core
pip install -e product
```

Editable (`-e`) links the installed package to your source, so every edit takes
effect immediately with no rebuild. Then just `python3 -m viva.web` / `pytest`
work with no `PYTHONPATH`.

**Or run against the source path** without installing:

```
cd product && PYTHONPATH=../core:. python3 -m viva.web
```

**Gotcha — a stale install shadows your edits.** If you ever ran a plain
`pip install core` / `pip install product` (non-editable), a *copy* landed in
site-packages and Python will import that, not your source — so a fix in the repo
appears to have no effect (e.g. `parse_date() got an unexpected keyword argument`
after the code already has it). Check which copy is live:

```
python3 -c "import vivacore; print(vivacore.__file__)"   # should be inside repo core/, not site-packages
```

If it points at site-packages, `pip uninstall -y vivacore viva` and use one of
the two methods above. (Never `pip install` the non-editable way for dev — and
`build/` and `dist/` are git-ignored so a stray build can't be committed.)

## Running the surface

```
# put VIVA_PASSPHRASE and (optionally) the model vars in product/.env, then:
PYTHONPATH=../core:. python3 -m viva.web        # or just: python3 -m viva.web  (if editable-installed)
# then open http://127.0.0.1:8765
```

The surface auto-loads `./.env` (git-ignored), so you don't have to export
anything — a `.env` with `VIVA_PASSPHRASE` (and, for live reading,
`VIVA_MODEL_ADAPTER` / `VIVA_MODEL` / `VIVA_MODEL_KEY_ENV` / the key) is enough.
Set `VIVA_SAMPLE=1` to seed fabricated data. Uploads park until a model is
configured, so nothing leaves the machine until you choose the real run.
- `viva/ingest/raw_store.py` — encrypted, content-addressed raw capture (every file, always).
- `viva/ingest/statement.py` — a model read → canonical `StatementFacts` (or a refusal).
- `viva/ingest/pipeline.py` — capture → classify → reconcile → post, or park (never discard).
- `viva/ingest/diagnose.py` — when reconciliation fails, localize it deterministically into a typed finding (forced / suggested / unlocalized).
- `viva/ingest/reader.py` — the one live model edge (text+image); left unrun until a real statement.

## Ingest, in one line

Every uploaded file is captured raw and encrypted first; a model *proposes* a
read; a recognized checking statement is posted only if it reconciles to the
cent (the gate), and everything else is *parked* — held and acknowledged, lit up
later when a projector for its type arrives, with no re-upload.

When a statement does not reconcile, deterministic diagnosis localizes it (no
model call): a correction an independent identity *forces* (the running-balance
chain) is auto-applied at `corroborated` and reported; a merely *suggested* one
is held for the human, shown against the source. See
[docs/verification-findings-and-correction.md](../docs/verification-findings-and-correction.md).

## Categorization: two mechanisms (design, deferred to a later increment)

A purchase is not one bucket. Splitting one purchase across categories *by amount*
is native double-entry (`split_transaction`); attaching *overlapping labels* to
the same money is the many-to-many `tags` overlay on a transaction. The ledger is
built so both are already possible — v0 seeds neither.

## Tests

Run from the repo root against the in-tree packages (no install needed):

```
PYTHONPATH=core:product python3 -m pytest product/tests -q
```
