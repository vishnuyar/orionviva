"""The ingest pipeline: capture → classify → verify → post.

Every file that arrives is:

  1. **Captured raw and encrypted, first.** Content-addressed, so a re-upload is
     a no-op rather than a duplicate.
  2. **Read by a model.** The read is a proposal; nothing downstream trusts it
     on its own.
  3. **Routed by type through the registry.** A classified type resolves to a
     profile; the balance family (checking, savings, credit card) shares one and
     goes to the reconciliation gate. A type with no profile is *parked* — held
     and acknowledged, never discarded — and posts retroactively once one is
     registered, with no re-upload.
  4. **Gated by deterministic reconciliation.** A statement posts only if
     opening + its transactions equal the printed closing to the cent. Otherwise
     it is surfaced as a conflict and not posted.

Across months of the same account the pipeline *stitches*: a later statement's
opening must equal the balance already held, or the document is held as a gap.

The model read is injected (``read_fn``), so everything here runs offline
against fixtures; only ``reader`` touches the network.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from decimal import Decimal
from typing import Callable

from vivacore.verify.arithmetic import (CheckResult, check_balance_identity,
                                        check_brokerage_identity,
                                        check_paystub_identity)

from ..ledger.events import (CORROBORATED, VERIFIED, Provenance, account_opened,
                             closing_balance_observed, document_captured,
                             opening_balance_observed, position_observed,
                             read_recorded, statement_held)
from ..ledger.ledger import Ledger
from ..ledger.postings import (brokerage_activity_transaction,
                               brokerage_cash_effect, paystub_decomposition,
                               simple_transaction)
from .brokerage import BrokerageFacts
from .diagnose import FORCED, SUGGESTED, UNLOCALIZED, ReconciliationFinding, diagnose
from ..ledger.identity import account_key
from .paystub import PayStubFacts
from .raw_store import RawStore
from .registry import (BALANCE_IDENTITY, BROKERAGE_IDENTITY, INVESTMENT,
                       PAYSTUB_IDENTITY, account_kind_for, can_project,
                       identity_of_facts, profile_for)
from .statement import StatementFacts, TxnFact

log = logging.getLogger(__name__)


from .pipeline_models import *
from .statement_projector import *
from .paystub_projector import *
from .brokerage_projector import *

def sweep(ledger: Ledger) -> dict:
    """Run the whole reconciliation + transfer sweep over an existing vault.

    Stitches gaps, closes conflict-holds a counterparty now corroborates, posts
    pay stubs whose deposit has arrived, and links internal transfers among all
    posted movements. Makes no model calls. Idempotent — already-linked
    movements and resolved holds are skipped — so it is safe on startup or on
    demand. Returns counts of `gaps`, `corroborated`, `auto`, `suggested`,
    `resolved`, `open_before` and `links`."""
    from .transfers import link_transfers
    # Corroboration re-posts run their own transfer scan, so the trailing
    # link_transfers alone undercounts; diff the projection instead.
    p0 = ledger.projection()
    links0, sugg0 = len(p0.transfer_links()), len(p0.transfer_suggestions())
    gaps = heal_gaps(ledger)
    corroborated = heal_corroboration(ledger)
    gaps += heal_paystubs(ledger)         # awaiting pay stubs whose deposit is here
    link_transfers(ledger)
    p1 = ledger.projection()
    auto = len(p1.transfer_links()) - links0
    # `suggested` is the number of questions open NOW, not a delta: a link
    # resolves the suggestions on both its legs, so a difference nets two
    # unrelated movements and means nothing on its own.
    open_now = len(p1.transfer_suggestions())
    if gaps or corroborated or auto or open_now != sugg0:
        log.info("sweep: %d gaps healed, %d corroborated, %d transfers auto-linked, "
                 "%d question(s) open (was %d)",
                 gaps, corroborated, auto, open_now, sugg0)
    return {"gaps": gaps, "corroborated": corroborated, "auto": auto,
            "suggested": open_now, "resolved": max(0, sugg0 - open_now),
            "open_before": sugg0, "links": len(p1.transfer_links())}



def capture_and_ingest(raw: RawStore, ledger: Ledger, data: bytes,
                       read_fn: ReadFn, filename: str = "",
                       captured_at: str = "") -> IngestResult:
    """Raw-capture a file, read it, and either post it or park it.

    Returns an ``IngestResult``; a file whose content has already been ingested
    comes back as DUPLICATE without being read again, and a read that raises is
    recorded as a failed read and parked rather than lost."""
    doc_id = raw.put(data)                       # (1) capture first, always
    log.info("ingest start: %s (%d bytes) doc_id=%s",
             filename or "<upload>", len(data), doc_id[:12])
    if ledger.projection().is_resolved(doc_id):
        log.info("ingest: doc_id=%s already posted/held — skipping", doc_id[:12])
        return IngestResult(doc_id=doc_id, action=DUPLICATE, doc_type="",
                            message="Already posted or held (same content); no change.")

    try:
        rr = read_fn(data, doc_id)               # (2) the model read (a proposal)
    except DocumentTooLarge as e:
        # Refused rather than failed, and refused for a reason no later arrival
        # changes: the document is kept, and the message says so instead of
        # promising it will be understood when some projector shows up.
        log.info("ingest: refused doc_id=%s as too costly to read: %s",
                 doc_id[:12], e)
        ledger.append(document_captured(
            doc_id, filename, len(data), "unknown", 0.0, captured_at,
            Provenance(doc_id=doc_id)))
        return IngestResult(
            doc_id=doc_id, action=PARKED, doc_type="",
            message=(f"Captured and kept, not read: {e}. Nothing was read from "
                     "it, so nothing from it is on your books. Splitting it, or "
                     "raising the limit, is what changes that."))
    except Exception as e:                       # a read that threw is recorded, not orphaned
        log.warning("ingest: read raised for doc_id=%s: %s", doc_id[:12], e)
        rr = ReadResult("unknown", 0.0, None, error=f"read failed: {e}",
                        model="(read error)")
    log.info("ingest: read doc_id=%s -> doc_type=%r conf=%.2f facts=%s error=%s",
             doc_id[:12], rr.doc_type, rr.doc_type_confidence,
             rr.facts is not None, rr.error)

    ledger.append(document_captured(             # record that it is held
        doc_id, filename, len(data), rr.doc_type, rr.doc_type_confidence,
        captured_at, Provenance(doc_id=doc_id)))

    # The claims layer: persist the verbatim model output for any real read. A
    # two-phase read records one ReadRecorded per phase (classify + extract); a
    # legacy single-call reader (or stub) records one via the flat fields.
    if rr.phases:
        for ph in rr.phases:
            ledger.append(read_recorded(
                doc_id, ph.model, ph.prompt_version, ph.input_mode, ph.raw_text,
                ph.cost_usd, ph.input_tokens, ph.output_tokens, ph.parse_ok,
                ph.error, captured_at, Provenance(doc_id=doc_id), phase=ph.phase))
            log.info("ingest: stored ReadRecorded phase=%s (model=%s cost=$%.4f "
                     "parse_ok=%s resp_chars=%d)", ph.phase, ph.model, ph.cost_usd,
                     ph.parse_ok, len(ph.raw_text))
    elif rr.model:
        ledger.append(read_recorded(
            doc_id, rr.model, rr.prompt_version, rr.input_mode, rr.raw_text,
            rr.cost_usd, rr.input_tokens, rr.output_tokens,
            rr.facts is not None, rr.error, captured_at, Provenance(doc_id=doc_id)))
        log.info("ingest: stored ReadRecorded (model=%s cost=$%.4f parse_ok=%s "
                 "resp_chars=%d)", rr.model, rr.cost_usd, rr.facts is not None,
                 len(rr.raw_text))

    # (3) route by type: the registry says which types have a projector.
    if rr.facts is not None and can_project(rr.doc_type):
        # (4) route by the profile's identity to that identity's gate and
        # post-projector.
        profile = profile_for(rr.doc_type)
        identity = profile.identity if profile is not None else ""
        if identity == PAYSTUB_IDENTITY:
            res = post_paystub(ledger, rr.facts)
        elif identity == BROKERAGE_IDENTITY:
            res = post_brokerage(ledger, rr.facts)
        else:
            res = post_statement(ledger, rr.facts)
        if res.action == POSTED:
            healed = heal_gaps(ledger)           # this post may unblock a gap hold
            # ...may corroborate a conflict-held statement
            healed += heal_corroboration(ledger)
            # ...may be the deposit a held pay stub was waiting for
            healed += heal_paystubs(ledger)
            if healed:
                log.info("ingest: healed %d previously-held statement(s)", healed)
            # (5) new movements may complete an internal transfer with movements
            # already held. The import is deferred to break an ingest cycle.
            from .transfers import link_transfers
            link_transfers(ledger)
        log.info("ingest done: doc_id=%s -> %s (%s)", doc_id[:12], res.action, res.grade)
        return res

    reason = rr.error or f"no projector yet for '{rr.doc_type or 'unknown'}'"
    log.info("ingest done: doc_id=%s -> parked (%s)", doc_id[:12], reason)
    return IngestResult(
        doc_id=doc_id, action=PARKED, doc_type=rr.doc_type,
        message=(f"Captured and held; not yet readable ({reason}). It will be "
                 "understood when a projector for its type arrives."))
