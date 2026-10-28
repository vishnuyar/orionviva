"""Runner-owned current-context allocation selection and target resolution."""
from dataclasses import replace
from fractions import Fraction
import hashlib,json,re,secrets,threading
from time import monotonic
from .allocation_continuation import (DeliveredAllocationRegistry,RecoveryAnchor,SelectionManifest,VERSION,source_commitment,validate_selection)
from .allocation_target import parse_allocation_target
from .instrument_claims import ResolvedTargetPremise

class InstrumentConversationContext:
    def __init__(self,vault_id,supplier):
        self.registry=DeliveredAllocationRegistry(vault_id);self.supplier=supplier
        self.targets={};self.target_commitments={};self.epoch=0;self.delivery_lock=threading.RLock();self.current_selection_ids=()

    def reset(self):
        with self.delivery_lock:
            self.registry.reset();self.targets.clear();self.target_commitments.clear();self.current_selection_ids=();self.epoch+=1

    def _read(self,deadline):
        return self.supplier(deadline=deadline) if getattr(self.supplier,"deadline_aware",False) else self.supplier()

    def _validate(self,manifest,revision,deadline):
        return validate_selection(manifest,revision,deadline=deadline)

    def recover(self,anchor):
        from .read_store.allocation_continuation import load_selection
        deadline=monotonic()+2
        with self._read(deadline) as revision:
            revision._store.authenticated_source_identity(revision)
            ids=self.registry.recover(anchor,load=lambda t,a:load_selection(revision,t,a),
                validate=lambda m:self._validate(m,revision,deadline))
            self.current_selection_ids=ids
            return ids

    def prepare_target(self,parameters,sources,context,families):
        from .answer_program.schema import ContractError
        from .read_store.instrument_authority_contracts import InstrumentRequest
        from .read_store.instrument_authority import read_instrument_authority
        try:
            if context is None:raise ValueError("allocation target needs current question context")
            parsed=parse_allocation_target(context.question)
            if type(sources) is not dict or set(sources)!=set(parameters):raise ValueError("target proof must name every parameter exactly")
            for name in ("target_percent","exposure"):
                proof=sources[name]
                expected=parsed.target_role_text if name=="target_percent" else parsed.exposure_text
                if type(proof) is not dict or set(proof)!={"source","quote","derivation"} or proof!={"source":"question","quote":expected,"derivation":"verbatim"}:
                    raise ValueError("target role/exposure must quote the current unmodified question")
            percent=parameters["target_percent"]
            if type(percent) is not str or re.fullmatch(r"(?:0|[1-9][0-9]{0,2})(?:\.[0-9]{1,12})?",percent) is None or Fraction(percent)/100!=Fraction(parsed.target_numerator,parsed.target_denominator):
                raise ValueError("target value differs from its current role")
            if parameters["exposure"]!=parsed.exposure:raise ValueError("target exposure differs from current question")
            explicit_account=None
            if parsed.account_text and not parsed.continuation_reference:
                rows=families._account_role_candidates(parsed.account_text)
                if len(rows)!=1:raise ValueError("clarify the allocation account")
                explicit_account=rows[0]["id"]
                if parameters.get("account_phrase") not in (parsed.account_text,explicit_account):raise ValueError("allocation account substitution")
                proof=sources.get("account_phrase")
                if not proof or proof.get("source")!="question" or proof.get("quote")!=parsed.account_text:raise ValueError("allocation account needs its current source")
            elif "account_phrase" in parameters:
                raise ValueError("continuation cannot provide an invented account parameter")
            if "as_of" in parameters and parameters["as_of"]!=parsed.as_of:raise ValueError("allocation date substitution")
            if parsed.as_of is not None:
                proof=sources.get("as_of")
                if not proof or proof.get("source")!="question" or proof.get("quote")!=parsed.date_text:raise ValueError("allocation date needs its current source")
            deadline=monotonic()+2
            with self._read(deadline) as revision:
                available=[]
                eligible=tuple(getattr(context,"allocation_selection_ids",()))
                for receipt_id in eligible:
                    try:
                        record=self.registry.resolve(receipt_id,vault_id=self.registry.vault_id,session_id=self.registry.session_id,
                            validate=lambda m:self._validate(m,revision,deadline))
                    except ValueError:continue
                    m=record.manifest
                    if m.axis!="exposure" or (parsed.as_of is not None and m.snapshot_date!=parsed.as_of) or (explicit_account is not None and m.account!=explicit_account):continue
                    available.append(record)
                needs_selection=parsed.continuation_reference or explicit_account is None or parsed.as_of is None
                selected=None
                if needs_selection:
                    focuses={(r.manifest.account,r.manifest.currency,r.manifest.snapshot_date) for r in available}
                    if len(focuses)!=1:raise ValueError("clarify the selected allocation account and snapshot date")
                    wanted=parameters.get("continuation_receipt_id")
                    if wanted is not None and wanted not in {r.receipt_id for r in available}:raise ValueError("unissued or incompatible continuation ID")
                    selected=next((r for r in available if r.receipt_id==wanted),available[-1])
                    if wanted is not None:
                        proof=sources["continuation_receipt_id"]
                        if type(proof) is not dict or proof.get("source")!="question" or proof.get("quote") not in (parsed.account_text,"last allocation answer"):
                            raise ValueError("continuation needs the current explicit reference")
                    m=selected.manifest;account=m.account;currency=m.currency;as_of=parsed.as_of or m.snapshot_date
                else:
                    if "continuation_receipt_id" in parameters:raise ValueError("unexpected continuation target")
                    account=explicit_account;as_of=parsed.as_of
                    currency=families.resolve_instrument_currency(account)
                    if not currency:raise ValueError("selected account currency unavailable")
                request=InstrumentRequest("allocation",account,currency,as_of=as_of,axis="exposure")
                actual=read_instrument_authority(revision,request,deadline=deadline)
                if actual.focus is None or not actual.selection_dependencies:raise ValueError("accepted allocation snapshot unavailable")
                premise=ResolvedTargetPremise(secrets.token_urlsafe(24),context.question_id,account,currency,parsed.exposure,as_of,
                    parsed.target_numerator,parsed.target_denominator,parsed.target_role_span,parsed.exposure_span,
                    parsed.target_role_text,parsed.exposure_text,parsed.percent_unit,selected.receipt_id if selected else "",tuple(actual.selection_dependencies))
                self.targets.clear();self.target_commitments.clear()
                self.targets[premise.receipt_id]=premise;self.target_commitments[premise.receipt_id]=source_commitment(actual)
                return {"account_phrase":account,"currency":currency,"as_of":as_of,"exposure":parsed.exposure,"target_premise_ref":premise.receipt_id}
        except (ValueError,TypeError,KeyError) as error:raise ContractError(str(error)) from error

    def validate_target(self,premise,revision,question,*,deadline):
        from .read_store.instrument_authority_contracts import InstrumentRequest
        from .read_store.instrument_authority import read_instrument_authority
        if self.targets.get(premise.receipt_id) is not premise:return False
        if question[premise.target_role_span[0]:premise.target_role_span[1]]!=premise.target_role_text:return False
        actual=read_instrument_authority(revision,InstrumentRequest("allocation",premise.account,premise.currency,as_of=premise.as_of,axis="exposure"),deadline=deadline)
        return tuple(actual.selection_dependencies)==premise.dependencies and source_commitment(actual)==self.target_commitments.get(premise.receipt_id)

    def manifests(self,turn,turn_id,answer_id):
        if not turn.result.answered:return ()
        execution=getattr(turn,"instrument_execution",None)
        if execution is None:return ()
        bindings=turn.result.bindings
        delivered={f.get("id") for f in turn.result.figures}
        out=[]
        for result in execution.transcript:
            authority=result.instrument_selection
            if authority is None or authority.focus is None:continue
            f=authority.focus
            selected=[v for v in result.figures if v.get("id") in delivered and v.get("claim","").startswith("allocation_") and v.get("claim")!="allocation_percentage_points"]
            if not selected:continue
            identity=hashlib.sha256(json.dumps({"program":turn.program,"bindings":bindings,"account":f.account,"date":f.snapshot_date},sort_keys=True,separators=(",",":")).encode()).hexdigest()
            m=SelectionManifest(VERSION,turn_id,answer_id,f.account,f.currency,f.snapshot_date,f.axis,f.exposure,authority.revision,tuple(authority.selection_dependencies),source_commitment(authority),identity)
            if m not in out:out.append(m)
        if len(out)>4:return ()
        return tuple(out)

    def delivered(self,manifests,turn_id,answer_id):
        if not manifests:return ()
        deadline=monotonic()+2
        with self._read(deadline) as revision:
            ids=self.registry.issue_delivered(manifests,turn_id=turn_id,answer_id=answer_id,delivered=True,
                validate=lambda m:self._validate(m,revision,deadline))
            self.current_selection_ids=ids
            return ids
