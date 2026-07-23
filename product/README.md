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
