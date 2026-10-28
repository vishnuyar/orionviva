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
                       PAYSTUB_IDENTITY, INSTRUMENT_IDENTITY, account_kind_for, can_project,
                       identity_of_facts, profile_for)
from .statement import StatementFacts, TxnFact

log = logging.getLogger(__name__)


from .pipeline_models import *
from .statement_projector import *
from .paystub_projector import *
from .brokerage_projector import *
from .instrument_projector import post_instrument, heal_instruments


def _finalize_posted_documents(ledger: Ledger, posted_before: set[str]) -> None:
    """Give every document posted by an ingestion cascade a complete category pair."""
    from .categorize import assign_default_categories

    newly_posted = ledger.projection().posted_doc_ids() - posted_before
    for doc_id in sorted(newly_posted):
        assign_default_categories(ledger, doc_id)

def sweep(ledger: Ledger) -> dict:
    """Run the whole reconciliation + transfer sweep over an existing vault.

    Stitches gaps, closes conflict-holds a counterparty now corroborates, posts
    pay stubs whose deposit has arrived, and links internal transfers among all
    posted movements. Makes no model calls. Idempotent — already-linked
    movements and resolved holds are skipped — so it is safe on startup or on
    demand. Returns counts of `gaps`, `corroborated`, `auto`, `suggested`,
    `resolved`, `open_before` and `links`."""
    from .transfers import link_transfers
    from ..listen import repair_asserted_account_aliases
    # Corroboration re-posts run their own transfer scan, so the trailing
    # link_transfers alone undercounts; diff the projection instead.
    p0 = ledger.projection()
    posted_before = p0.posted_doc_ids()
    links0, sugg0 = len(p0.transfer_links()), len(p0.transfer_suggestions())
    accounts_merged = repair_asserted_account_aliases(ledger)
    gaps = heal_gaps(ledger)
    corroborated = heal_corroboration(ledger)
    gaps += heal_paystubs(ledger)         # awaiting pay stubs whose deposit is here
    heal_instruments(ledger)
    link_transfers(ledger)
    _finalize_posted_documents(ledger, posted_before)
    p1 = ledger.projection()
    auto = len(p1.transfer_links()) - links0
    # `suggested` is the number of questions open NOW, not a delta: a link
    # resolves the suggestions on both its legs, so a difference nets two
    # unrelated movements and means nothing on its own.
    open_now = len(p1.transfer_suggestions())
    review_movements = sorted({item.get("a", "")
                               for item in p1.transfer_suggestions()
                               if item.get("a", "")})
    if gaps or corroborated or auto or open_now != sugg0:
        log.info("sweep: %d gaps healed, %d corroborated, %d transfers auto-linked, "
                 "%d question(s) open (was %d)",
                 gaps, corroborated, auto, open_now, sugg0)
    return {"gaps": gaps, "corroborated": corroborated, "auto": auto,
            "suggested": open_now, "resolved": max(0, sugg0 - open_now),
            "open_before": sugg0, "links": len(p1.transfer_links()),
            "accounts_merged": accounts_merged,
            "review_movements": review_movements}



def capture_and_ingest(raw: RawStore, ledger: Ledger, data: bytes,
                       read_fn: ReadFn, filename: str = "",
                       captured_at: str = "", *, on_captured=None,
                       before_read=None, _retained_audit=None, _bulk_audit=None) -> IngestResult:
    """Keep one document's read and posting exclusive through its result."""
    if _bulk_audit is not None:
        _check_bulk_owner(_bulk_audit,raw,ledger,data)
        return _capture_and_ingest(raw,ledger,data,read_fn,filename,captured_at,
            on_captured=on_captured,before_read=before_read,_bulk_audit=_bulk_audit)
    with raw.document_lock(raw.fingerprint(data)):
        return _capture_and_ingest(raw, ledger, data, read_fn, filename,
                                   captured_at, on_captured=on_captured,
                                   before_read=before_read, _retained_audit=_retained_audit)


def _capture_and_ingest(raw: RawStore, ledger: Ledger, data: bytes,
                       read_fn: ReadFn, filename: str = "",
                       captured_at: str = "", *, on_captured=None,
                       before_read=None, _retained_audit=None, _bulk_audit=None) -> IngestResult:
    """Raw-capture a file, read it, and either post it or park it.

    Returns an ``IngestResult``; a file whose content has already been ingested
    comes back as DUPLICATE without being read again, and a read that raises is
    recorded as a failed read and parked rather than lost."""
    doc_id = (_bulk_audit.document if _bulk_audit is not None and _bulk_audit.retained
              else raw.put(data))  # A retained owner already authenticated its original.
    if on_captured is not None:
        on_captured(doc_id)
    log.info("ingest start: %s (%d bytes) doc_id=%s",
             filename or "<upload>", len(data), doc_id[:12])
    if ledger.projection().is_resolved(doc_id):
        log.info("ingest: doc_id=%s already posted/held — skipping", doc_id[:12])
        return IngestResult(doc_id=doc_id, action=DUPLICATE, doc_type="",
                            message="Already posted or held (same content); no change.")
    posted_before = ledger.projection().posted_doc_ids()
    if before_read is not None:
        before_read(doc_id)

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
        from ..sample.curation import CuratedReader, RetainedCuratedReader
        if isinstance(read_fn, (CuratedReader, RetainedCuratedReader)):
            raise
        log.warning("ingest: read raised for doc_id=%s: %s", doc_id[:12], e)
        rr = ReadResult("unknown", 0.0, None, error=f"read failed: {e}",
                        model="(read error)")
    log.info("ingest: read doc_id=%s -> doc_type=%r conf=%s facts=%s error=%s",
             doc_id[:12], rr.doc_type, rr.doc_type_confidence,
             rr.facts is not None, rr.error)

    mixed_acquisition = rr.acquisition is not None and bool(
        rr.model or rr.phases or rr.resolved_model or rr.cost_usd
        or rr.input_tokens or rr.output_tokens or rr.usage_reported)
    if mixed_acquisition:
        # Keep the real attempted model receipt while refusing forged local metadata.
        rr = replace(rr, acquisition=None, facts=None,
                     error=("model results cannot claim local acquisition" if rr.model or rr.phases
                            else "unsupported producer state: model activity has no configured route"))

    if _retained_audit is not None:
        _validate_retained_replay(_retained_audit, ledger, data, rr)

    if _bulk_audit is not None:
        _validate_bulk_read(_bulk_audit,rr)
    if _bulk_audit is None or _bulk_audit.capture is None:
        ledger.append(document_captured(             # record that it is held
        doc_id, filename, len(data), rr.doc_type, rr.doc_type_confidence,
            captured_at, Provenance(doc_id=doc_id), acquisition=rr.acquisition))

    # Persist each phase's verbatim model output. Readers exposing only the flat
    # result fields produce one recorded read.
    if _retained_audit is not None or _bulk_audit is not None:
        pass  # Exact original receipts are already retained by their checked owner.
    elif rr.acquisition is not None:
        from ..ledger.events import curated_read_recorded
        if (rr.model or rr.phases or rr.prompt_version or rr.resolved_model
                or rr.cost_usd or rr.input_tokens or rr.output_tokens or rr.usage_reported):
            raise ValueError("curation cannot suppress model activity")
        ledger.append(curated_read_recorded(doc_id, rr.doc_type, rr.raw_text,
            rr.facts is not None, rr.error, captured_at, rr.acquisition))
    elif rr.phases:
        for ph in rr.phases:
            ledger.append(read_recorded(
                doc_id, ph.model, ph.prompt_version, ph.input_mode, ph.raw_text,
                ph.cost_usd, ph.input_tokens, ph.output_tokens, ph.parse_ok,
                ph.error, captured_at, Provenance(doc_id=doc_id), phase=ph.phase,
                resolved_model=ph.resolved_model,
                usage_reported=ph.usage_reported,
                normalization_context=ph.normalization_context))
            log.info("ingest: stored ReadRecorded phase=%s (model=%s cost=$%.4f "
                     "parse_ok=%s resp_chars=%d)", ph.phase, ph.model, ph.cost_usd,
                     ph.parse_ok, len(ph.raw_text))
    elif rr.model or mixed_acquisition:
        receipt = read_recorded(
            doc_id, rr.model, rr.prompt_version, rr.input_mode, rr.raw_text,
            rr.cost_usd, rr.input_tokens, rr.output_tokens,
            rr.facts is not None, rr.error, captured_at, Provenance(doc_id=doc_id),
            resolved_model=rr.resolved_model,
            usage_reported=rr.usage_reported,
            normalization_context=rr.normalization_context)
        if mixed_acquisition and not rr.model:
            receipt.body['unsupported_producer_metadata'] = {
                'configured_route_available': False,
                'input_tokens': rr.input_tokens, 'output_tokens': rr.output_tokens,
                'usage_reported': rr.usage_reported}
        ledger.append(receipt)
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
        elif identity == INSTRUMENT_IDENTITY:
            res = post_instrument(ledger, rr.facts)
        else:
            res = post_statement(ledger, rr.facts)
        heal_instruments(ledger)
        if identity == INSTRUMENT_IDENTITY and rr.doc_type in ("mortgage_statement", "refinance_settlement"):
            from .apr_context_local import extract_apr_context
            extract_apr_context(raw, ledger, doc_id, locale=rr.source_locale)
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
        from viva.investment.healing import heal_after_source
        heal_after_source(ledger, doc_id)
        _finalize_posted_documents(ledger, posted_before)
        log.info("ingest done: doc_id=%s -> %s (%s)", doc_id[:12], res.action, res.grade)
        return res

    reason = rr.error or f"no projector yet for '{rr.doc_type or 'unknown'}'"
    log.info("ingest done: doc_id=%s -> parked (%s)", doc_id[:12], reason)
    return IngestResult(
        doc_id=doc_id, action=PARKED, doc_type=rr.doc_type,
        message=(f"Captured and held; not yet readable ({reason}). It will be "
                 "understood when a projector for its type arrives."))


# Internal replay capabilities are issued only from an authenticated original
# event-store snapshot plus its original encrypted raw documents. They never
# accept model/client-supplied event dictionaries.
_RETAINED_AUDIT_ISSUER = object()

@dataclass(frozen=True)
class _AuthenticatedReplaySource:
    issuer: object
    identity: object
    entries: tuple
    documents: object
    eligible: frozenset

    def events(self):
        from ..ledger.events import Event
        return tuple(Event.from_dict(entry.event.to_dict()) for entry in self.entries)

@dataclass(frozen=True)
class _RetainedAuditPermit:
    issuer: object
    ledger: object
    document: str
    selected: bytes
    records: tuple


def _audit_bytes(event):
    import json
    return json.dumps(event.to_dict(), sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False).encode('utf-8')


def _capture_authenticated_replay(source, raw):
    """Capture one source prefix. Original bodies/IDs stay deeply immutable."""
    import hashlib
    from types import MappingProxyType
    if type(source) is not Ledger or type(raw) is not RawStore:
        raise ValueError('authenticated replay source and original raw store required')
    snapshot = source.store.committed_snapshot()
    events = tuple(entry.event for entry in snapshot.events)
    eligible = frozenset(event.body.get('doc_id') for event in events
        if event.event_type == 'ReadRecorded' and
        ('normalization_context' in event.body or 'acquisition' in event.body
         or 'transport_complete' in event.body))
    audit_docs=eligible | frozenset(event.body.get('doc_id') for event in events
        if event.event_type=='ModelExtractionResponseRecorded')
    from ..extraction_responses import validate_links
    preceding=[]
    for event in events:
        if event.event_type=='ReadRecorded':validate_links(event.body,preceding)
        preceding.append(event)
    documents = {}
    for doc in audit_docs:
        if type(doc) is not str or not doc:
            raise ValueError('retained audit document binding unavailable')
        data = raw.get(doc)
        if hashlib.sha256(data).hexdigest() != doc:
            raise ValueError('retained audit raw document identity differs')
        captures = [event for event in events if event.event_type == 'DocumentCaptured'
                    and event.body.get('doc_id') == doc]
        if not captures or any(event.body.get('byte_len') != len(data) or
                event.provenance.get('doc_id') not in ('', doc) for event in captures):
            raise ValueError('retained audit captured document binding differs')
        documents[doc] = data
    # Validate all identities before any destination writes, including foreign
    # IDs outside the selected document population.
    identities = {}
    extract_docs={event.body.get('doc_id') for event in events
        if event.event_type=='ReadRecorded' and event.body.get('phase','extract')=='extract'}
    orphan_docs=audit_docs-extract_docs
    copied_ids = {event.event_id for event in events
        if event.body.get('doc_id') in audit_docs and
        (event.event_type in ('ReadRecorded','ModelExtractionResponseRecorded') or
         event.event_type=='DocumentCaptured' and event.body.get('doc_id') in orphan_docs)}
    for entry in snapshot.events:
        if entry.event_id not in copied_ids:continue
        event = entry.event
        wire = _audit_bytes(event)
        if event.event_id in identities and identities[event.event_id] != wire:
            raise ValueError('original event identity is ambiguous')
        identities[event.event_id] = wire
        if event.provenance.get('doc_id') not in ('', event.body['doc_id']):
            raise ValueError('retained audit belongs to another document')
        if 'acquisition' in event.body:
            from ..sample.curation import decode_retained_input
            decode_retained_input(event.to_dict()['body'])
    return _AuthenticatedReplaySource(_RETAINED_AUDIT_ISSUER, snapshot.identity,
        snapshot.events, MappingProxyType(documents), eligible)


def _retain_authenticated_replay(capture, raw, ledger):
    """Copy audit only, in original relative source order, once per identity.

    No parse, financial event, new model receipt, usage or charge is created.
    Financial reconstruction remains the caller's separate latest-phase path.
    """
    from ..ledger.events import Event
    from ..ledger.projection import LedgerProjection
    if (type(capture) is not _AuthenticatedReplaySource or
            capture.issuer is not _RETAINED_AUDIT_ISSUER or
            type(raw) is not RawStore or type(ledger) is not Ledger):
        raise ValueError('backend authenticated replay capability required')
    for doc, data in capture.documents.items():
        if raw.put(data) != doc:raise ValueError('destination raw document differs')
    originals = []; seen = set(); selected = {}
    extract_docs={entry.event.body.get('doc_id') for entry in capture.entries
        if entry.event.event_type=='ReadRecorded' and entry.event.body.get('phase','extract')=='extract'}
    orphan_docs=set(capture.documents)-extract_docs
    for entry in capture.entries:
        event = entry.event
        if event.body.get('doc_id') not in capture.documents:continue
        if not (event.event_type in ('ReadRecorded','ModelExtractionResponseRecorded') or
                event.event_type=='DocumentCaptured' and event.body.get('doc_id') in orphan_docs):
            continue
        if event.event_type=='ReadRecorded':
            from ..extraction_responses import validate_links
            validate_links(event.body,[item for item in originals])
            selected[(event.body['doc_id'], event.body.get('phase', 'extract'))] = event
        if event.event_id not in seen:
            originals.append(event);seen.add(event.event_id)
    by_id = {event.event_id: _audit_bytes(event) for event in originals}
    source_order = [event.event_id for event in originals]
    def decide(projection):
        events = tuple(projection._source_events)
        retained = []
        for event in events:
            if event.event_id in by_id:
                if _audit_bytes(event) != by_id[event.event_id]:
                    raise ValueError('destination retained audit identity collision')
                if event.event_id in retained:
                    raise ValueError('destination duplicates an original receipt identity')
                retained.append(event.event_id)
        if retained != source_order[:len(retained)]:
            raise ValueError('destination retained audit order is ambiguous')
        missing = tuple(Event.from_dict(event.to_dict()) for event in originals[len(retained):])
        # Prove the entire audit fold before the atomic append; a malformed
        # local envelope cannot leave a newly trusted partial financial state.
        LedgerProjection((*events, *missing), resolve_keys=ledger._resolve_keys)
        return missing
    ledger.append_atomically(decide)
    return {doc: _RetainedAuditPermit(_RETAINED_AUDIT_ISSUER, ledger, doc,
                _audit_bytes(selected[(doc, 'extract')]),
                tuple((event.event_id, _audit_bytes(event)) for event in originals
                      if event.body.get('doc_id') == doc))
            for doc in capture.eligible if (doc, 'extract') in selected}


def _validate_retained_replay(permit, ledger, data, rr):
    import hashlib,json
    if (type(permit) is not _RetainedAuditPermit or
            permit.issuer is not _RETAINED_AUDIT_ISSUER or permit.ledger is not ledger or
            hashlib.sha256(data).hexdigest() != permit.document or rr.phases):
        raise ValueError('retained replay is not bound to this original document')
    selected = json.loads(permit.selected)
    if rr.raw_text != selected['body'].get('response_text', ''):
        raise ValueError('retained replay changed original parser input')
    events = tuple(ledger.events());expected = dict(permit.records);latest = None
    for event in events:
        if event.event_id in expected and _audit_bytes(event) != expected[event.event_id]:
            raise ValueError('retained replay original body changed')
        if (event.event_type == 'ReadRecorded' and event.body.get('doc_id') == permit.document
                and event.body.get('phase', 'extract') == 'extract'):
            latest = event
    if latest is None or _audit_bytes(latest) != permit.selected:
        raise ValueError('selected retained extraction changed')


_BULK_ISSUER=object()

@dataclass
class _BulkReadOwner:
    issuer: object
    raw: object
    ledger: object
    document: str
    filename: str
    data: bytes
    dated: str
    lock: object
    active: bool=True
    capture: object=None
    records: list=field(default_factory=list)
    responses: list=field(default_factory=list)
    audit_order: list=field(default_factory=list)
    retained: bool=False
    original_prefix: tuple=()
    original_captures: tuple=()
    original_audit: tuple=()
    capture_commitment: str=''
    known_type: str='unknown'


    def close(self):
        if self.active:
            self.active=False
            self.lock.__exit__(None,None,None)


def _begin_bulk_read(raw,ledger,data,filename,dated):
    document=raw.fingerprint(data)
    held=raw.document_lock(document);held.__enter__()
    try:
        if raw.put(data)!=document:raise ValueError('bulk original identity changed')
        return _BulkReadOwner(_BULK_ISSUER,raw,ledger,document,filename,data,dated,held)
    except BaseException:
        held.__exit__(None,None,None);raise


def _check_bulk_owner(owner,raw,ledger,data):
    if (type(owner) is not _BulkReadOwner or owner.issuer is not _BULK_ISSUER or not owner.active
            or owner.raw is not raw or owner.ledger is not ledger or owner.data!=data
            or raw.fingerprint(data)!=owner.document):
        raise ValueError('foreign or expired bulk read ownership')


def _bulk_phase_event(owner,phase):
    return read_recorded(owner.document,phase.model,phase.prompt_version,phase.input_mode,
        phase.raw_text,phase.cost_usd,phase.input_tokens,phase.output_tokens,phase.parse_ok,
        phase.error,owner.dated,Provenance(doc_id=owner.document),phase=phase.phase,
        resolved_model=phase.resolved_model,usage_reported=phase.usage_reported,
        normalization_context=phase.normalization_context,
        transport_receipt_ids=phase.transport_receipt_ids,transport_complete=phase.transport_complete,
        extraction_id=phase.extraction_id,phase_attempt=phase.phase_attempt)


def _retain_bulk_phase(owner,phase,doc_type,confidence):
    _check_bulk_owner(owner,owner.raw,owner.ledger,owner.data)
    if type(phase) is not ModelPhase or phase.phase not in ('classify','extract'):
        raise ValueError('closed model phase required')
    if phase.transport_complete is False and phase.parse_ok:
        raise ValueError('incomplete transport cannot be a successful phase')
    _retain_bulk_original(owner,doc_type,confidence)
    event=_bulk_phase_event(owner,phase)
    from ..extraction_responses import validate_links
    validate_links(event.body,owner.ledger.events())
    owner.ledger.append(event);owner.records.append(event.to_dict());owner.audit_order.append(event.to_dict())


def _retain_bulk_response(owner,body):
    _check_bulk_owner(owner,owner.raw,owner.ledger,owner.data)
    if body.get('doc_id')!=owner.document:raise ValueError('foreign response document')
    from ..ledger.events import model_extraction_response_recorded
    _retain_bulk_original(owner)
    event=model_extraction_response_recorded(body,owner.dated)
    owner.ledger.append(event);owner.responses.append(event.to_dict());owner.audit_order.append(event.to_dict())
    return event.event_id


def _validate_bulk_history(owner):
    """Check exact retained history even when a late reader loses its result."""
    _check_bulk_owner(owner,owner.raw,owner.ledger,owner.data)
    source=tuple(owner.ledger.events())
    if owner.retained:
        if tuple(_audit_bytes(event) for event in source[:len(owner.original_prefix)])!=owner.original_prefix:
            raise ValueError('retained canonical prefix changed')
        captures=tuple(event.to_dict() for event in source if event.event_type=='DocumentCaptured' and event.body.get('doc_id')==owner.document)
        if captures!=owner.original_captures:raise ValueError('retained capture population changed')
    expected=(list(owner.original_audit)+owner.audit_order if owner.retained else
              ([owner.capture] if owner.capture is not None else [])+owner.audit_order)
    ids={record['event_id'] for record in expected}
    retained=[event.to_dict() for event in source if event.event_id in ids]
    if retained!=expected:
        raise ValueError('bulk capture or phase identity/order/multiplicity changed')
    actual=[event.event_id for event in source if event.event_type=='ReadRecorded'
            and event.body.get('doc_id')==owner.document]
    if actual!=[record['event_id'] for record in (*owner.original_audit,*owner.records) if record['event_type']=='ReadRecorded']:
        raise ValueError('bulk document acquired another reading')
    response_ids=[event.event_id for event in source
        if event.event_type=='ModelExtractionResponseRecorded' and event.body.get('doc_id')==owner.document]
    if response_ids!=[record['event_id'] for record in (*owner.original_audit,*owner.responses) if record['event_type']=='ModelExtractionResponseRecorded']:
        raise ValueError('bulk document acquired another extraction response')
    return source


def _validate_bulk_read(owner,rr):
    import json
    if owner.retained:
        if any(phase.transport_complete is not True or not phase.transport_receipt_ids
               or not phase.extraction_id for phase in rr.phases):
            raise ValueError('retained reading requires complete scoped raw acknowledgements')
        if rr.facts is not None and (not rr.phases or rr.phases[-1].phase!='extract'
                                    or rr.phases[-1].parse_ok is not True):
            raise ValueError('retained facts require the latest accepted extraction phase')
    if owner.retained and rr.facts is not None:
        from ..ledger.projection.coverage import canonical_classification
        kind,_,error=canonical_classification(rr.doc_type,rr.doc_type_confidence)
        if error or owner.known_type not in ('','unknown',kind):
            raise ValueError('retained classification contradicts capture')
    if rr.acquisition is not None or len(rr.phases)!=len(owner.records):
        raise ValueError('bulk reading changed its retained phase population')
    source=_validate_bulk_history(owner)
    events={event.event_id:event.to_dict() for event in source}
    for phase,record in zip(rr.phases,owner.records):
        if events.get(record['event_id'])!=record or _bulk_phase_event(owner,phase).body!=record['body']:
            raise ValueError('bulk reading changed retained receipt identity or body')
    if owner.capture is not None and events.get(owner.capture['event_id'])!=owner.capture:
        raise ValueError('bulk original capture receipt changed')
    if rr.facts is not None and any(phase.transport_complete is False for phase in rr.phases):
        raise ValueError('incomplete transport cannot supply accepted facts')
    if rr.error is not None and rr.facts is not None:
        raise ValueError('failed bulk reading cannot supply accepted facts')


def _retain_bulk_original(owner,doc_type='unknown',confidence=0.0):
    _check_bulk_owner(owner,owner.raw,owner.ledger,owner.data)
    if owner.capture is None:
        capture=document_captured(owner.document,owner.filename,len(owner.data),doc_type,confidence,
            owner.dated,Provenance(doc_id=owner.document))
        owner.ledger.append(capture);owner.capture=capture.to_dict()



def _begin_retained_bulk_read(raw, ledger, document, dated):
    """Authenticate a saved original and freeze its old audit under its lock."""
    from .pipeline_models import retained_capture_commitment
    from .reader import MAX_BYTES
    held=raw.document_lock(document);held.__enter__()
    try:
        from ..crypto import VERSION
        import json
        # Closed AES-GCM envelope: 16-byte tag, base64 ceiling and exact JSON overhead.
        envelope_overhead=len(json.dumps({'v':VERSION,'nonce':'A'*16,'ct':''},ensure_ascii=False).encode())
        data=raw.get_bounded(document,max_plaintext=MAX_BYTES,
            max_envelope=4*((MAX_BYTES+18)//3)+envelope_overhead)
        if raw.fingerprint(data)!=document:raise ValueError('capture_conflict')
        source=tuple(ledger.events())
        captures=tuple(json.loads(_audit_bytes(event)) for event in source
            if event.event_type=='DocumentCaptured' and event.body.get('doc_id')==document)
        if not captures:raise ValueError('evidence_unavailable')
        latest=captures[-1]; body=latest['body']
        identity=(body.get('filename'),body.get('doc_type'),body.get('byte_len'))
        if any((record['body'].get('filename'),record['body'].get('doc_type'),record['body'].get('byte_len'))!=identity for record in captures):
            raise ValueError('capture_conflict')
        size=body.get('byte_len')
        if type(size) is not int or size!=len(data):raise ValueError('capture_conflict')
        if any(record['provenance'].get('doc_id')!=document or 'acquisition' in record['body'] for record in captures):
            raise ValueError('evidence_unavailable')
        projection=ledger.projection()
        if projection.is_resolved(document):raise ValueError('financial_review')
        allowed={'DocumentCaptured','ReadRecorded','ModelExtractionResponseRecorded'}
        audit=[]; responses=[]; reads=[]
        from ..extraction_responses import validate_links,validate_response_body
        from ..ledger.projection.coverage import classified_claim,canonical_classification
        linked=[];classifications=[]
        def references(value):
            if type(value) is dict:return any(references(v) for v in value.values())
            if type(value) in (list,tuple):return any(references(v) for v in value)
            return value==document
        for event in source:
            belongs=(references(event.body) or event.to_dict().get('provenance',{}).get('doc_id')==document)
            if not belongs:continue
            if event.event_type not in allowed:raise ValueError('financial_review')
            if event.event_type=='ModelExtractionResponseRecorded':
                validate_response_body(event.body);responses.append(event);audit.append(json.loads(_audit_bytes(event)))
            elif event.event_type=='ReadRecorded':
                claim=event.body
                if claim.get('phase')=='extract' and claim.get('parse_ok') is not False:raise ValueError('already_accepted')
                if (claim.get('phase') not in ('classify','extract') or 'acquisition' in claim
                        or claim.get('transport_complete') is not True or not claim.get('transport_receipt_ids')):
                    raise ValueError('uncertain_audit')
                validate_links(claim,responses)
                if claim['phase']=='classify':
                    classified=classified_claim(event,responses)
                    if classified is None:raise ValueError('uncertain_audit')
                    classifications.append(classified[0])
                reads.append(event);audit.append(json.loads(_audit_bytes(event)));linked.extend(claim['transport_receipt_ids'])
        if len(reads)>10000 or len(responses)>10000:raise ValueError('evidence_unavailable')
        if linked!=[event.event_id for event in responses]:raise ValueError('uncertain_audit')
        known=body.get('doc_type','unknown')
        canonical,_,error=canonical_classification(known,body.get('doc_type_confidence',0))
        if error:raise ValueError('capture_conflict')
        if canonical not in ('','unknown') and any(kind!=canonical for kind in classifications):
            raise ValueError('capture_conflict')
        if len(set(classifications))>1:raise ValueError('capture_conflict')
        commitment=retained_capture_commitment(document,body.get('filename'),body.get('doc_type'),latest['event_id'])
        return _BulkReadOwner(_BULK_ISSUER,raw,ledger,document,body['filename'],data,dated,held,
            capture=latest,retained=True,original_prefix=tuple(_audit_bytes(e) for e in source),
            original_captures=captures,original_audit=tuple(audit),capture_commitment=commitment,
            known_type=canonical if canonical not in ('','unknown') else classifications[0] if classifications else 'unknown')
    except BaseException:
        held.__exit__(None,None,None);raise
