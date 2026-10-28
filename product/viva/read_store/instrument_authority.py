"""Six closed source-bound instrument views over one immutable read revision."""
from dataclasses import replace, fields, is_dataclass
from datetime import date, timedelta
from decimal import Decimal
from hashlib import sha256
from time import monotonic
import json
from .instrument_authority_contracts import (InstrumentRequest,InstrumentAuthorityResult,
    AuthorityNumeric,AuthorityAssertion,AuthorityAnchor,AuthorityDisposition,AuthorityCoverage,AuthorityFocus,AuthorityRelationship)
from .instrument_authority_sql import source_snapshot,allocation_snapshot,account_currency,check_deadline,AuthorityReadError,resolve_account_reference,receiving_relationship,witnessed_loan_zero,restriction_status
from .instrument_math import (decimal_fraction,source_rate_fraction,allocation_points,rational,_mul,_bounded,_decimal_text,InstrumentMathError)
from ..instrument_claims import CLAIMS,ResolvedTargetPremise
from ..ingest import instrument_contracts as c


def _id(*parts):
    return sha256(json.dumps(parts,ensure_ascii=False,separators=(',',':')).encode()).hexdigest()


def _sum(values):
    n,d=0,1
    for value in values:
        other_n,other_d=decimal_fraction(value)
        n,d=rational(_bounded(_mul(n,other_d)+_mul(other_n,d)),_mul(d,other_d))
    return _decimal_text(n,d)


def _weight(numerator,denominator):
    n,d=decimal_fraction(numerator); total_n,total_d=decimal_fraction(denominator)
    if not total_n:
        raise AuthorityReadError('unavailable zero allocation denominator')
    n,d=rational(_mul(n,total_d),_mul(d,total_n))
    quotient,remainder=divmod(_mul(n,10**16),d)
    if _mul(remainder,2)>d or (_mul(remainder,2)==d and quotient%2):
        quotient=_bounded(quotient+1)
    return _decimal_text(quotient,10**16),remainder==0


class _View:
    def __init__(self,revision,request,deadline):
        self.revision,self.request,self.deadline=revision,request,deadline
        self.figures=[]; self.assertions=[]; self.anchors={}; self.dispositions=[]; self.coverage=[]
        self.dependencies=set(); self.focus=None; self.relationships=[]; self.source_rows=0
        self.snapshot=source_snapshot(revision,request,deadline)
        self.states={state.observation_id:{r.component:r for r in state.components} for state in self.snapshot.component_states}
        self.rows=[row['change'] for row in self.snapshot.observations]
        row_types={c.DepositMovement,c.PrincipalMovement,c.PaymentComponents,c.EscrowMovement,c.ClosingFee,c.PositionClassification}
        from dataclasses import fields,is_dataclass
        def count_rows(value):
            if type(value) in row_types:
                self.source_rows+=1
                if self.source_rows>1000:raise AuthorityReadError('resource_limit')
            if is_dataclass(value):
                for field in fields(value):count_rows(getattr(value,field.name))
            elif type(value) is tuple:
                for child in value:count_rows(child)
        for row in self.rows:count_rows(row.payload)

    def accepted(self,row,component):
        result=self.states.get(row.observation_id,{}).get(component)
        if result is None or result.disposition != c.Disposition.ACCEPTED:
            disposition='unavailable' if result is None else result.disposition.value
            entry=AuthorityDisposition(component,disposition,(row.observation_id,),'' if result is None else result.reason)
            if entry not in self.dispositions:
                self.dispositions.append(entry)
            return False
        self.dependencies.add(row.observation_id)
        return True

    def anchor(self,source):
        if type(source) is not c.Source:
            raise AuthorityReadError('unavailable complete page evidence')
        key=_id(source.doc_id,source.page)
        self.anchors[key]=AuthorityAnchor(key,source.doc_id,source.page)
        if len(self.anchors)>512:
            raise AuthorityReadError('resource_limit')
        return key

    def number(self,claim,value,row,component,*,dated=None,start=None,end=None,sources=(),grade='corroborated',exact=True,premise=None,operands=(),account=None,record_association=None,calculation_context=None):
        check_deadline(self.deadline)
        if len(self.figures)>=80:
            raise AuthorityReadError('resource_limit')
        source=getattr(value,'source',None)
        if isinstance(value,c.Rate):
            number=source_rate_fraction(value.percent)
        elif isinstance(value,c.Money):
            if value.currency!=self.request.currency:
                raise AuthorityReadError('unavailable currency mismatch')
            number=_decimal_text(*decimal_fraction(value.value))
        else:
            number=str(value)
        anchors=tuple(sorted({self.anchor(s) for s in ((source,) if source else ()) + tuple(sources)}))
        if not anchors:
            anchors=(self.anchor(row.source),)
        currency=None if CLAIMS[claim].render_type in {'rate','percentage_points','count'} else self.request.currency
        figure=AuthorityNumeric(_id(claim,row.observation_id,component,dated,start,end,number,*((record_association,) if record_association else ())),claim,number,
            account or self.request.account,currency,dated,start,end,anchors,(row.observation_id,),(component,),grade,exact,
            CLAIMS[claim].direction or None,premise,operands,record_association,calculation_context)
        self.figures.append(figure)
        if not getattr(row,'source_snapshot',False):self.dependencies.add(row.observation_id)
        return figure

    def assertion(self,claim,value,row,component,source=None,account=None,record_association=None):
        if value is None:
            return
        source=source or getattr(value,'source',None)
        raw=getattr(value,'value',value)
        contract=CLAIMS[claim]
        if contract.value_type=='enum':
            raw=getattr(value,'value',value)
        receipt=AuthorityAssertion(_id(claim,row.observation_id,component,raw,*((record_association,) if record_association else ())),claim,raw,account or self.request.account,
            row.effective.value,(self.anchor(source),),(row.observation_id,),(component,),'corroborated',record_association=record_association)
        self.assertions.append(receipt); self.dependencies.add(row.observation_id)

    def finish(self):
        if not self.figures and not self.assertions and not self.dispositions:
            self.dispositions.append(AuthorityDisposition(self.request.view,'unavailable',reason='No applicable accepted source records.'))
        return InstrumentAuthorityResult(self.request,self.revision.generation,tuple(self.figures),tuple(self.assertions),
            tuple(self.anchors.values()),tuple(self.dispositions),tuple(self.coverage),tuple(sorted(self.dependencies)),self.focus,tuple(self.relationships))


def _terms(view):
    request=view.request
    candidates=[]
    for row in view.rows:
        if row.subject_id!=request.account or row.effective.value>request.as_of:
            continue
        terms=getattr(row.payload,'terms',None)
        component='deposit_terms' if isinstance(terms,c.DepositTerms) else 'mortgage_terms'
        if terms is not None and view.accepted(row,component):
            candidates.append((row,terms,component))
    deposits=[item for item in candidates if isinstance(item[1],c.DepositTerms)]
    if deposits:
        opened=max(item[1].opened.value for item in deposits if item[1].opened.value<=request.as_of)
        candidates=[item for item in deposits if item[1].opened.value==opened]
    numeric={}; assertions={}
    for row,terms,component in candidates:
        fields=(('deposit_contract_principal','principal'),('deposit_nominal_rate','rate')) if isinstance(terms,c.DepositTerms) else (
            ('loan_original_principal','original_principal'),('loan_note_rate','note_rate'),('loan_disclosure_apr','disclosure_apr'),('loan_term_months','term_months'))
        for claim,field in fields:
            value=getattr(terms,field)
            if value is not None:
                fingerprint=str(getattr(value,'value',getattr(value,'percent',value)))
                numeric.setdefault(claim,{}).setdefault(fingerprint,[]).append((row,component,value,getattr(terms,field+'_source',None)))
        fields=(('deposit_opened','opened'),('deposit_maturity','maturity'),('deposit_compounding','compounding'),
            ('deposit_withdrawal_restriction','withdrawal_restriction'),('deposit_rate_basis','rate_basis'),('deposit_day_count','day_count')) if isinstance(terms,c.DepositTerms) else (
            ('loan_originated','originated'),('loan_maturity','maturity'),('loan_fixed_rate','fixed_rate'),('loan_note_rate_basis','note_rate_basis'))
        for claim,field in fields:
            value=getattr(terms,field)
            source=getattr(value,'source',None) or getattr(terms,field+'_source',None)
            if value is not None and source is not None:
                fingerprint=getattr(value,'value',value)
                assertions.setdefault(claim,{}).setdefault(fingerprint,[]).append((row,component,value,source))
    for claim,values in numeric.items():
        if len(values)!=1:
            view.dispositions.append(AuthorityDisposition(claim,'conflicted'));continue
        witnesses=next(iter(values.values()));row,component,value,source=witnesses[-1]
        figure=view.number(claim,value,row,component,dated=row.effective.value,sources=tuple(s or getattr(v,'source',r.source) for r,_,v,s in witnesses))
        view.figures[-1]=replace(figure,observation_ids=tuple(sorted({r.observation_id for r,_,_,_ in witnesses})))
    for claim,values in assertions.items():
        if len(values)!=1:
            view.dispositions.append(AuthorityDisposition(claim,'conflicted'));continue
        witnesses=next(iter(values.values()));row,component,value,source=witnesses[-1]
        view.assertion(claim,value,row,component,source)
        view.assertions[-1]=replace(view.assertions[-1],anchor_ids=tuple(sorted({view.anchor(s) for _,_,_,s in witnesses})),
            observation_ids=tuple(sorted({r.observation_id for r,_,_,_ in witnesses})))
    from .apr_context_sql import select_context
    for field,claim in (('status','disclosure_apr_status'),('context','disclosure_apr_context')):
        contextual=[]
        for row,terms,component in candidates:
            if not isinstance(terms,c.MortgageTerms):continue
            selection=select_context(view.snapshot,loan_id=request.account,numeric_terms_observation_id=row.observation_id,
                effective_date=row.effective.value,field=field)
            if selection.result.disposition=='accepted':contextual.append((row,selection))
            elif selection.result.disposition=='conflicted':
                view.dispositions.append(AuthorityDisposition(claim,'conflicted',selection.observation_ids))
        if contextual:
            if len({selection.result.value for _,selection in contextual})!=1:
                view.dispositions.append(AuthorityDisposition(claim,'conflicted',tuple(sorted({i for _,selection in contextual for i in selection.observation_ids}))))
                continue
            row,selection=max(contextual,key=lambda item:(item[0].effective.value,item[0].observation_id))
            result=selection.result
            view.assertions.append(AuthorityAssertion(_id(claim,*selection.observation_ids),claim,result.value,request.account,
                row.effective.value,(view.anchor(result.source),),selection.observation_ids,('mortgage_terms',),'corroborated',
                row.observation_id,result.grounding))
            view.dependencies.update(selection.observation_ids);view.dependencies.add(row.observation_id)
    _endpoint(view,request.as_of)
    availability=[row for row in view.rows if row.subject_id==request.account and row.kind.value=='availability' and row.effective.value<=request.as_of]
    status=restriction_status(view.revision,request,availability,view.deadline)
    if status!='accepted':view.dispositions.append(AuthorityDisposition('availability_restriction',status,tuple(row.observation_id for row in availability)))
    else:
        for row in availability:
            if row.payload.restriction is not None:
                view.assertion('availability_restriction',row.payload.restriction,row,'availability',row.payload.source)


def _endpoint(view,boundary):
    candidates=[]
    for row in view.rows:
        f=row.payload
        if row.subject_id!=view.request.account or getattr(f,'end',None) is None or f.end.value>boundary:
            continue
        if isinstance(f,c.DepositFacts) and view.accepted(row,'deposit_balance'):
            candidates.append((f.end.value,row,'deposit_balance','deposit_closing_balance',f.closing))
        elif isinstance(f,c.MortgageFacts) and view.accepted(row,'principal_balance'):
            candidates.append((f.end.value,row,'principal_balance','loan_closing_principal',f.closing_principal))
    if candidates:
        latest=max(item[0] for item in candidates); selected=[item for item in candidates if item[0]==latest]
        if len({str(item[4].value) for item in selected})!=1:
            view.dispositions.append(AuthorityDisposition('current_balance','conflicted'));return
        dated,row,component,claim,value=selected[-1]
        view.number(claim,value,row,component,dated=dated,sources=tuple(item[4].source for item in selected))


def _periods(view, *, payment_principal=False):
    if type(payment_principal) is not bool:raise ValueError("closed principal projection flag required")
    request=view.request
    events={};endpoints=[];coverage={};witnesses={}
    def cover(claims,row,component):
        for claim in claims:
            coverage.setdefault(claim,[]).append((row.payload.start.value,row.payload.end.value))
            witnesses.setdefault(claim,[]).append((row,component))
    for row in view.rows:
        f=row.payload
        if row.subject_id!=request.account or not isinstance(f,(c.DepositFacts,c.MortgageFacts)) or f.start is None or f.end is None:
            continue
        if f.end.value<request.start or f.start.value>request.end:continue
        if isinstance(f,c.DepositFacts):
            if request.component_set!='deposit' or not view.accepted(row,'deposit_balance'):continue
            claims={c.DepositKind.INTEREST:'deposit_credited_interest',c.DepositKind.FUNDING:'deposit_funding',c.DepositKind.REDEMPTION:'deposit_redemption'}
            cover(tuple(claims.values()),row,'deposit_balance')
            for movement in f.movements or ():
                if movement.kind in claims:
                    _flow_event(view,events,row,'deposit_balance',claims[movement.kind],movement.amount,movement.dated,movement.reference)
            endpoints.append((row,'deposit_balance','deposit_opening_balance',f.opening,'deposit_closing_balance',f.closing))
            continue
        if request.component_set=='deposit':continue
        principal_ok=view.accepted(row,'principal_balance')
        if principal_ok and request.component_set in {'loan_principal','annual_summary'}:
            cover(('principal_repayment','principal_payoff'),row,'principal_balance')
            for movement in f.principal_movements or ():
                if movement.kind in {c.PrincipalKind.REDUCTION,c.PrincipalKind.PAYOFF}:
                    claim='principal_repayment' if movement.kind==c.PrincipalKind.REDUCTION else 'principal_payoff'
                    _flow_event(view,events,row,'principal_balance',claim,movement.amount,movement.dated,movement.reference)
        if principal_ok:
            endpoints.append((row,'principal_balance','loan_opening_principal',f.opening_principal,'loan_closing_principal',f.closing_principal))
        if request.component_set in {'payment_escrow','annual_summary'}:
            payment_claims=(('payment_interest','interest'),('payment_fees','fees'),('escrow_funding','escrow'),('payment_total','total'))
            if payment_principal:payment_claims+=(("payment_principal","principal"),)
            payment_components=[('payment:'+p.reference.value if p.reference else 'payment:unresolved') for p in f.payments or ()]
            eligible={claim:[] for claim,_ in payment_claims}
            for payment,component in zip(f.payments or (),payment_components):
                printed=view.accepted(row,component)
                known=next((allocation for allocation in view.snapshot.known_allocations
                    if allocation.receipt.observation_id==row.observation_id and allocation.payment==payment),None)
                reconciled=known is not None and view.accepted(row,'known_allocation:'+payment.reference.value)
                if not printed and not reconciled:
                    continue
                for claim,field in payment_claims:
                    value=getattr(payment,field)
                    if value is not None:
                        eligible[claim].append((payment,component,value,known if reconciled else None))
                    elif field=='fees':
                        view.dispositions.append(AuthorityDisposition(claim,'unavailable',(row.observation_id,),'Fee amount is not printed; known components reconcile to cash.'))
                if reconciled and request.grouping!='year':
                    receipt=known.receipt
                    sources=tuple(getattr(payment,field).source for field in ('total','principal','interest','escrow'))+(receipt.bank_source,)
                    view.number('payment_net_unallocated','0',row,'known_allocation:'+payment.reference.value,
                        dated=payment.dated.value,start=payment.dated.value,end=payment.dated.value,sources=sources,grade=receipt.grade,
                        operands=receipt.operand_ids,record_association=receipt.occurrence_id+':'+receipt.cash_event_id,
                        calculation_context='printed_payment_net_residual_v1')
            for claim,_ in payment_claims:
                rows=eligible[claim]
                if f.payments is not None and len(rows)==len(f.payments) and (claim!='payment_principal' or rows):
                    cover((claim,),row,'payments')
                    for payment,component,value,known in rows:
                        _flow_event(view,events,row,component,claim,value,payment.dated,payment.reference)
            if f.escrow is not None and view.accepted(row,'escrow_balance'):
                cover(('tax_paid',),row,'escrow_balance')
                for movement in f.escrow.movements or ():
                    if movement.kind==c.EscrowKind.TAX:
                        _flow_event(view,events,row,'escrow_balance','tax_paid',movement.amount,movement.dated,movement.reference)
                endpoints.append((row,'escrow_balance','escrow_opening_balance',f.escrow.opening,'escrow_closing_balance',f.escrow.closing))
    allowed=set()
    for claim,periods in coverage.items():
        before=len(view.coverage);_coverage(view,periods)
        if view.coverage[-1].complete:allowed.add(claim)
        else:view.dispositions.append(AuthorityDisposition(claim,'unavailable',reason='Accepted source periods do not completely cover the requested period.'))
    if not coverage:
        _coverage(view,())
        view.dispositions.append(AuthorityDisposition('period_totals','unavailable',reason='No complete accepted source component coverage.'))
    grouped={}
    for (claim,dated,reference),records in events.items():
        if claim not in allowed:continue
        if len({str(item[2].value) for item in records})!=1:
            view.dispositions.append(AuthorityDisposition(claim,'conflicted'));allowed.discard(claim);continue
        group=dated if request.grouping=='none' else dated[:7] if request.grouping=='month' else dated[:4]
        grouped.setdefault((claim,group),[]).append(records)
    groups={key[1] for key in grouped}
    if request.grouping=='month' and len(groups)>12 or request.grouping=='year' and len(groups)>10:
        raise AuthorityReadError('resource_limit')
    for (claim,group),collections in sorted(grouped.items()):
        if claim not in allowed:continue
        records=[record for collection in collections for record in collection]
        row,component,_,dated,reference=records[0]
        amount=_sum(collection[0][2].value for collection in collections)
        start,end=_group_bounds(request,group)
        known=[allocation for allocation in view.snapshot.known_allocations if any(
            allocation.receipt.observation_id==record[0].observation_id and allocation.payment.reference.value==record[4]
            for record in records)]
        sources=tuple(record[2].source for record in records)
        for allocation in known:
            sources+=tuple(getattr(allocation.payment,field).source for field in ('total','principal','interest','escrow'))+(allocation.bank_source,)
        figure=view.number(claim,amount,row,component,start=start,end=end,sources=sources,
            grade='unverified' if known else 'corroborated',operands=tuple(dict.fromkeys(
                operand for allocation in known for operand in allocation.receipt.operand_ids)))
        view.figures[-1]=replace(figure,observation_ids=tuple(sorted({r[0].observation_id for r in records})),component_ids=tuple(sorted({r[1] for r in records})))
        if claim=='payment_principal' and known:
            view.figures[-1]=replace(view.figures[-1],component_ids=tuple(sorted(set(view.figures[-1].component_ids)|{
                'known_allocation:'+allocation.payment.reference.value for allocation in known})))

    # Endpoint stocks stay separate from grouped flows and require their own
    # complete accepted principal/deposit/escrow coverage.
    if request.grouping=='month':
        first,last=date.fromisoformat(request.start),date.fromisoformat(request.end)
        groups=[f'{(first.year*12+first.month-1+offset)//12:04d}-{(first.year*12+first.month-1+offset)%12+1:02d}'
            for offset in range((last.year-first.year)*12+last.month-first.month+1)]
    elif request.grouping=='year':
        groups=[str(year) for year in range(date.fromisoformat(request.start).year,date.fromisoformat(request.end).year+1)]
    else:groups=['']
    _empty_month_tax_totals(view,allowed,groups,grouped)
    for group in groups:
        bound_start,bound_end=_group_bounds(request,group) if group else (request.start,request.end)
        eligible=[item for item in endpoints if item[0].payload.start.value<=bound_end and item[0].payload.end.value>=bound_start]
        for opening in (True,False):
            if not eligible:continue
            for claim in sorted({item[2 if opening else 4] for item in eligible}):
                candidates=[item for item in eligible if item[2 if opening else 4]==claim]
                all_periods=[(item[0].payload.start.value,item[0].payload.end.value) for item in endpoints if item[2 if opening else 4]==claim]
                if not _period_complete(all_periods,request.start,request.end):continue
                periods=[(item[0].payload.start.value,item[0].payload.end.value) for item in candidates]
                if not _period_complete(periods,bound_start,bound_end):continue
                boundary=bound_start if opening else bound_end
                selected=[item for item in candidates if (item[0].payload.start.value if opening else item[0].payload.end.value)==boundary]
                if not selected:continue
                if len({str(item[3 if opening else 5].value) for item in selected})!=1:
                    view.dispositions.append(AuthorityDisposition(claim,'conflicted'));continue
                row,component,_,_,_,_=selected[-1]
                figure=view.number(claim,selected[-1][3 if opening else 5],row,component,dated=boundary,
                    sources=tuple(item[3 if opening else 5].source for item in selected))
                view.figures[-1]=replace(figure,observation_ids=tuple(sorted({item[0].observation_id for item in selected})))


def _source_pages(value):
    """Retain every page witness of the accepted exhaustive component."""
    if type(value) is c.Source:
        return (value,)
    if is_dataclass(value):
        return tuple(source for field in fields(value) for source in _source_pages(getattr(value,field.name)))
    if type(value) is tuple:
        return tuple(source for child in value for source in _source_pages(child))
    return ()


def _empty_month_tax_totals(view,allowed,groups,grouped):
    request=view.request
    if request.grouping!='month' or request.component_set!='payment_escrow' or 'tax_paid' not in allowed:
        return
    first,last=date.fromisoformat(request.start),date.fromisoformat(request.end)
    next_month=date(last.year+1,1,1) if last.month==12 else date(last.year,last.month+1,1)
    if first.day!=1 or last!=next_month-timedelta(days=1):return
    for group in groups:
        check_deadline(view.deadline)
        start,end=_group_bounds(request,group)
        if ('tax_paid',group) in grouped:continue
        candidates=[row for row in view.rows if row.subject_id==request.account and isinstance(row.payload,c.MortgageFacts)
            and row.payload.start is not None and row.payload.end is not None
            and row.payload.start.value<=end and row.payload.end.value>=start]
        if not candidates or not _period_complete([(r.payload.start.value,r.payload.end.value) for r in candidates],start,end):continue
        valid=True;has_tax=False;sources=[];event_amounts={};period_witnesses={}
        for row in candidates:
            escrow=row.payload.escrow
            state=view.states.get(row.observation_id,{}).get('escrow_balance')
            if state is None or state.disposition!=c.Disposition.ACCEPTED or escrow is None or escrow.movements is None:
                valid=False;break
            if escrow.opening is None or escrow.closing is None or any(m.currency!=request.currency for m in (escrow.opening,escrow.closing)):
                valid=False;break
            local=set();signature=[]
            for movement in escrow.movements:
                if movement.kind is None or movement.amount is None or movement.dated is None or movement.reference is None or movement.amount.currency!=request.currency or not row.payload.start.value<=movement.dated.value<=row.payload.end.value:
                    valid=False;break
                decimal_fraction(movement.amount.value)
                key=(movement.kind,movement.dated.value,movement.reference.value)
                amount=decimal_fraction(movement.amount.value)
                if key in local or key in event_amounts and event_amounts[key]!=amount:
                    valid=False;break
                local.add(key);event_amounts[key]=amount
                signature.append((movement.kind.value,movement.dated.value,movement.reference.value,amount,
                    movement.property_reference.value if movement.property_reference else None,movement.tax_year))
                if movement.kind==c.EscrowKind.TAX and start<=movement.dated.value<=end:has_tax=True
            if not valid:break
            period=(row.payload.start.value,row.payload.end.value)
            fingerprint=tuple(sorted(signature,key=repr))
            if period in period_witnesses and period_witnesses[period]!=fingerprint:
                valid=False;break
            period_witnesses[period]=fingerprint
            sources.extend((row.source,)+_source_pages((row.payload.start,row.payload.end,escrow)))
        if not valid or has_tax:continue
        # Accepted instrument component evidence has the existing corroborated
        # grade; no stronger grade is inferred from event absence.
        figure=view.number('tax_paid','0',candidates[0],'escrow_balance',start=start,end=end,
            sources=tuple(sources),calculation_context='accepted_empty_tax_event_set_v1')
        observation_ids=tuple(sorted({row.observation_id for row in candidates}))
        view.figures[-1]=replace(figure,observation_ids=observation_ids)
        view.dependencies.update(observation_ids)


def _flow_event(view,events,row,component,claim,amount,dated,reference):
    if amount is None or dated is None or reference is None:return
    if view.request.start<=dated.value<=view.request.end:
        events.setdefault((claim,dated.value,reference.value),[]).append((row,component,amount,dated.value,reference.value))


def _period_complete(periods,start,end):
    cursor=start
    for left,right in sorted(set(periods)):
        if left>cursor:break
        if right>=end:return True
        if right>=cursor:cursor=(date.fromisoformat(right)+timedelta(days=1)).isoformat()
    return False


def _coverage(view,periods):
    unique=tuple(sorted(set(periods)))
    view.coverage.append(AuthorityCoverage(view.request.start,view.request.end,_period_complete(unique,view.request.start,view.request.end),unique))


def _group_bounds(request,group):
    if request.grouping=='none':return group,group
    if request.grouping=='year':return max(request.start,group+'-01-01'),min(request.end,group+'-12-31')
    year,month=map(int,group.split('-'))
    last=date(year+1,1,1)-timedelta(days=1) if month==12 else date(year,month+1,1)-timedelta(days=1)
    return max(request.start,group+'-01'),min(request.end,last.isoformat())


def _maturities(view):
    _terms(view)
    view.figures[:]=[figure for figure in view.figures if figure.claim=='deposit_contract_principal']
    view.assertions[:]=[assertion for assertion in view.assertions if assertion.claim=='deposit_maturity']
    for row in view.rows:
        f=row.payload
        if row.subject_id!=view.request.account or not isinstance(f,c.DepositFacts) or not view.accepted(row,'deposit_balance'):continue
        for movement in f.movements or ():
            if movement.kind==c.DepositKind.REDEMPTION and movement.dated.value<=view.request.as_of:
                view.number('deposit_redemption',movement.amount,row,'deposit_balance',dated=movement.dated.value)
                view.assertion('redemption_date',movement.dated,row,'deposit_balance')
                view.assertion('redemption_reference',movement.reference,row,'deposit_balance')
                if not view.accepted(row,'counterpart:'+movement.reference.value):
                    view.dispositions.append(AuthorityDisposition('redemption_receiving_account','unavailable',(row.observation_id,),'Accepted receiving-account relationship is absent.'))
                else:
                    try:
                        account,doc,page,own,other=receiving_relationship(view.revision,view.request,movement,view.deadline)
                        view.relationships.append(AuthorityRelationship('redemption_receiving_account',account,
                            (view.anchor(movement.reference.source),view.anchor(c.Source(doc,page))),(row.observation_id,),movement.dated.value))
                        view.dependencies.update(('movement:'+own,'movement:'+other))
                    except AuthorityReadError as error:
                        view.dispositions.append(AuthorityDisposition('redemption_receiving_account','unavailable',(row.observation_id,),str(error)))


def _refinances(view):
    for row in view.rows:
        f=row.payload
        if row.subject_id!=view.request.account or not isinstance(f,c.RefinanceFacts) or not view.request.start<=f.dated.value<=view.request.end:continue
        components=view.states.get(row.observation_id,{})
        if not all(view.accepted(row,name) for name in ('settlement_sources_uses','settlement_fees','financed_fees')):
            view.dispositions.append(AuthorityDisposition('refinance','held',(row.observation_id,)));continue
        old_account=resolve_account_reference(view.revision,f.old_loan.account_reference.value,view.request.currency,view.deadline)
        new_account=resolve_account_reference(view.revision,f.new_loan.account_reference.value,view.request.currency,view.deadline)
        if new_account!=view.request.account:raise AuthorityReadError('unavailable replacement account mismatch')
        for role,account,source in (('refinance_old_loan',old_account,f.old_loan.account_reference.source),
                ('refinance_new_loan',new_account,f.new_loan.account_reference.source)):
            view.relationships.append(AuthorityRelationship(role,account,(view.anchor(source),),(row.observation_id,),f.dated.value))
        for claim,field in (('refinance_old_payoff','old_payoff_principal'),('refinance_new_advance','new_funded_principal'),
            ('refinance_borrower_contribution','borrower_contribution'),('refinance_cash_out','cash_out'),
            ('refinance_financed_costs','financed_costs'),('refinance_fees','total_fees')):
            view.number(claim,getattr(f,field),row,'refinance',dated=f.dated.value,account=old_account if claim=='refinance_old_payoff' else new_account)
        view.assertion('settlement_date',f.dated,row,'refinance');view.assertion('settlement_reference',f.reference,row,'refinance')
        view.assertion('refinance_old_account_reference',f.old_loan.account_reference,row,'refinance',account=old_account)
        view.assertion('refinance_new_account_reference',f.new_loan.account_reference,row,'refinance',account=new_account)
        if f.old_closing_principal is not None and f.old_closing_principal.value==0 and view.accepted(row,'old_loan_zero') and 'old_loan_payoff_link' not in components:
            view.number('refinance_old_zero',f.old_closing_principal,row,'old_loan_payoff_link',dated=f.dated.value,account=old_account)
        else:
            zeroes=witnessed_loan_zero(view.revision,old_account,f.dated.value,view.deadline)
            if zeroes:
                figure=view.number('refinance_old_zero','0',row,'principal_balance',dated=f.dated.value,account=old_account,
                    sources=tuple(c.Source(doc,page) for doc,page,_,_ in zeroes))
                view.figures[-1]=replace(figure,observation_ids=tuple(sorted({identifier for _,_,identifier,_ in zeroes})))
            else:view.dispositions.append(AuthorityDisposition('old_loan_zero','unavailable',(row.observation_id,)))


def _taxes(view):
    events={};periods=[]
    refs={r[0] for r in view.snapshot.references};resolved_references={}
    receipts=[r for r in view.rows if isinstance(r.payload,c.TaxReceiptFacts)]
    for row in view.rows:
        f=row.payload
        if not isinstance(f,c.MortgageFacts) or f.escrow is None or f.escrow.identity is None:continue
        e=f.escrow
        if e.identity.account_reference.value not in refs and (e.continuity_reference is None or e.continuity_reference.value not in refs):continue
        reference=e.identity.account_reference.value if e.identity.account_reference.value in refs else e.continuity_reference.value
        if reference not in resolved_references:
            resolved_references[reference]=resolve_account_reference(view.revision,reference,view.request.currency,view.deadline)
        if resolved_references[reference]!=view.request.account:
            raise AuthorityReadError('unavailable canonical escrow account mismatch')
        if not view.accepted(row,'escrow_balance'):continue
        periods.append((f.start.value,f.end.value))
        for movement in e.movements or ():
            if (movement.kind!=c.EscrowKind.TAX or movement.property_reference is None or movement.tax_year is None
                    or not view.request.start<=movement.dated.value<=view.request.end):continue
            key=(movement.dated.value,movement.reference.value,movement.property_reference.value,movement.tax_year)
            events.setdefault(key,[]).append((row,movement))
    _coverage(view,periods)
    if not view.coverage[-1].complete:
        view.dispositions.append(AuthorityDisposition('tax_totals','unavailable',reason='Accepted escrow periods are incomplete.'));return
    groups={}
    for (dated,reference,property_id,tax_year),records in sorted(events.items()):
        if len({str(m.amount.value) for _,m in records})!=1 or len({r.observation_id for r,_ in records})!=len(records):
            raise AuthorityReadError('unavailable ambiguous accepted tax event identity')
        row,movement=records[0]
        witnesses=[]
        for receipt in receipts:
            f=receipt.payload
            if (f.source_account_reference is None or f.source_account_reference.value not in refs
                    or f.reference.value!=reference or f.property_reference.value!=property_id or f.tax_year!=tax_year
                    or f.amount.currency!=view.request.currency or f.amount.value!=movement.amount.value
                    or abs((date.fromisoformat(f.dated.value)-date.fromisoformat(dated)).days)>3):continue
            if view.accepted(receipt,'tax_payment_link'):witnesses.append(receipt)
        association=_id('tax_payment_v1',view.request.account,view.request.currency,dated,reference,property_id,tax_year)
        group=dated[:4] if view.request.grouping=='year' else (dated,reference,property_id,tax_year)
        groups.setdefault(group,[]).append((records,witnesses))
        for claim,field in (('tax_payment_reference','reference'),('tax_payment_date','dated'),('property_identity','property_reference')):
            view.assertion(claim,getattr(movement,field),row,'escrow_balance',record_association=association)
            view.assertions[-1]=replace(view.assertions[-1],anchor_ids=tuple(sorted({view.anchor(getattr(m,field).source) for _,m in records})),
                observation_ids=tuple(sorted({r.observation_id for r,_ in records})))
    if view.request.grouping=='year' and len(groups)>10:raise AuthorityReadError('resource_limit')
    for group,collections in sorted(groups.items()):
        first_row,first=collections[0][0][0]
        amount=_sum(records[0][1].amount.value for records,_ in collections)
        sources=[movement.amount.source for records,_ in collections for _,movement in records]
        sources.extend(receipt.payload.amount.source for _,receipts in collections for receipt in receipts)
        ids=tuple(sorted({row.observation_id for records,receipts in collections for row in [*(r for r,_ in records),*receipts]}))
        if view.request.grouping=='year':
            start,end=_group_bounds(view.request,group)
            figure=view.number('tax_paid',amount,first_row,'escrow_balance',start=start,end=end,sources=tuple(sources))
        else:
            if len(collections)!=1:raise AuthorityReadError('unavailable ambiguous accepted tax event association')
            association=_id('tax_payment_v1',view.request.account,view.request.currency,first.dated.value,first.reference.value,first.property_reference.value,first.tax_year)
            figure=view.number('tax_paid',amount,first_row,'escrow_balance',dated=first.dated.value,sources=tuple(sources),record_association=association)
        view.figures[-1]=replace(figure,observation_ids=ids,component_ids=tuple(sorted({'escrow_balance',*(
            'tax_year:'+str(movement.tax_year) for records,_ in collections for _,movement in records)})))
        view.dependencies.update(ids)


def _allocation(view,premise):
    request=view.request
    dated,positions,cash,all_positions,all_cash=allocation_snapshot(view.revision,request,view.deadline)
    if request.target_premise_ref is not None:
        if type(premise) is not ResolvedTargetPremise or (premise.receipt_id,premise.account,premise.currency,premise.as_of)!=(request.target_premise_ref,request.account,request.currency,dated):
            raise AuthorityReadError('unavailable target premise binding')
    classifications={}
    for row in view.rows:
        if row.kind.value=='position_classification' and row.effective.value==dated:
            classifications.setdefault((row.payload.instrument.value,row.source.doc_id),[]).append(row)
    amounts={};sources=[];dependencies=[];unclassified=[]
    for sequence,instrument,amount,currency,grade,doc,page in all_positions:
        sources.append(c.Source(doc,page));dependencies.append('position:'+str(sequence))
    for sequence,amount,confirmed_by,doc,page in all_cash:
        sources.append(c.Source(doc,page));dependencies.append('balance:'+str(sequence))
    for sequence,instrument,amount,currency,grade,doc,page in positions:
        if currency!=request.currency or grade not in {'verified','corroborated'}:
            raise AuthorityReadError('unavailable accepted allocation valuation')
        decimal_fraction(amount)
        source=c.Source(doc,page);sources.append(source);dependencies.append('position:'+str(sequence))
        docs={position[5] for position in all_positions if position[1]==instrument}
        rows=[r for witness_doc in docs for r in classifications.get((instrument,witness_doc),[])]
        if any(not classifications.get((instrument,witness_doc)) for witness_doc in docs):
            rows=[]
        categories={getattr(row.payload,request.axis).value for row in rows}
        category=next(iter(categories)) if len(categories)==1 else 'unknown'
        if category=='unknown':unclassified.append(amount)
        for row in rows: view.dependencies.add(row.observation_id)
        amounts.setdefault(category,[]).append(amount)
    sequence,cash_amount,confirmed_by,doc,page=cash
    decimal_fraction(cash_amount);sources.append(c.Source(doc,page));dependencies.append('balance:'+str(sequence))
    amounts.setdefault('cash' if request.axis=='exposure' else 'other',[]).append(cash_amount)
    snapshot_grade='verified' if all(row[4]=='verified' for row in all_positions) and all(row[2]=='human' for row in all_cash) else 'corroborated'
    total=_sum([*(r[2] for r in positions),cash_amount])
    # A synthetic local record transports source identities without pretending to
    # be a ledger observation. All underlying persisted IDs remain dependencies.
    from types import SimpleNamespace
    record=SimpleNamespace(observation_id='snapshot:'+_id(request.account,dated,doc),source=sources[0],source_snapshot=True)
    actual_ids=tuple(sorted(set(dependencies)|view.dependencies))
    total_figure=view.number('allocation_total_value',total,record,'allocation_snapshot',dated=dated,sources=tuple(sources),grade=snapshot_grade)
    view.figures[-1]=replace(total_figure,observation_ids=actual_ids)
    unknown=_sum(unclassified)
    unknown_figure=view.number('allocation_unclassified_value',unknown,record,'allocation_snapshot',dated=dated,sources=tuple(sources),grade=snapshot_grade)
    view.figures[-1]=replace(unknown_figure,observation_ids=actual_ids)
    if decimal_fraction(total)[0]==0 or unclassified:
        view.dispositions.append(AuthorityDisposition('allocation_weights','unavailable',actual_ids,'Zero or unclassified denominator.'))
        return
    selected_value=None;selected_weight=None
    values=('bond','equity','cash','other','unknown') if request.axis=='exposure' else ('mutual_fund','etf','individual_security','other','unknown')
    for category in values:
        amount=_sum(amounts.get(category,()))
        figure=view.number('allocation_'+request.axis+'_'+category+'_value',amount,record,'allocation_snapshot',dated=dated,sources=tuple(sources),grade=snapshot_grade)
        view.figures[-1]=replace(figure,observation_ids=actual_ids)
        weight,exact=_weight(amount,total)
        figure=view.number('allocation_'+request.axis+'_'+category+'_weight',weight,record,'allocation_snapshot',dated=dated,sources=tuple(sources),grade=snapshot_grade,exact=exact,operands=(figure.record_id,total_figure.record_id))
        view.figures[-1]=replace(figure,observation_ids=actual_ids)
        if premise is not None and category==premise.exposure:selected_value,selected_weight=amount,figure
    view.dependencies.update(actual_ids)
    view.focus=AuthorityFocus(request.account,request.currency,dated,request.axis,premise.exposure if premise else None)
    if request.target_premise_ref is not None:
        difference=allocation_points(selected_value,total,premise.target_numerator,premise.target_denominator)
        figure=view.number('allocation_percentage_points',difference.value,record,'allocation_snapshot',dated=dated,sources=tuple(sources),grade=None,exact=difference.exact,premise=premise.receipt_id,operands=(*selected_weight.operand_ids,selected_weight.record_id))
        view.figures[-1]=replace(figure,observation_ids=actual_ids)


def read_instrument_authority(revision,request,*,deadline,target_premise=None):
    """Enforce the complete local view boundary before exposing any result."""
    if type(request) is not InstrumentRequest:
        raise ValueError('closed InstrumentRequest required')
    deadline=min(deadline,monotonic()+2.0)
    try:
        if account_currency(revision,request.account,deadline)!=request.currency:
            raise AuthorityReadError('unavailable currency mismatch')
        view=_View(revision,request,deadline)
        {'terms':_terms,'period_components':_periods,'maturities':_maturities,'refinances':_refinances,'tax_payments':_taxes,
            'allocation':lambda v:_allocation(v,target_premise)}[request.view](view)
        check_deadline(deadline)
        return view.finish()
    except (AuthorityReadError,InstrumentMathError,ValueError) as error:
        reason=str(error)
        disposition='resource_limit' if 'resource_limit' in reason else 'unavailable'
        return InstrumentAuthorityResult(request,revision.generation,dispositions=(AuthorityDisposition(request.view,disposition,reason=reason[:2048]),))


def read_payment_principal_report_authority(revision,request,*,deadline):
    """Read the dormant printed-payment report from an authenticated source revision."""
    if type(request) is not InstrumentRequest:
        raise ValueError('closed InstrumentRequest required')
    if (request.view!='period_components' or
            (request.component_set,request.grouping) not in {('payment_escrow','month'),('annual_summary','year')} or
            request.start[:4]!=request.end[:4] or
            (request.grouping=='month' and int(request.end[5:7])-int(request.start[5:7])>=3)):
        raise ValueError('unsupported internal payment report period')
    deadline=min(deadline,monotonic()+2.0)
    try:
        check_deadline(deadline)
        revision._store.authenticated_source_identity(revision)
        if account_currency(revision,request.account,deadline)!=request.currency:
            raise AuthorityReadError('unavailable currency mismatch')
        view=_View(revision,request,deadline)
        _periods(view,payment_principal=True)
        claims={'payment_principal','payment_interest','payment_total','escrow_funding','tax_paid'}
        if request.grouping=='month':claims|={'loan_opening_principal','loan_closing_principal','escrow_opening_balance','escrow_closing_balance'}
        view.figures[:]=[figure for figure in view.figures if figure.claim in claims]
        anchors={anchor for figure in view.figures for anchor in figure.anchor_ids}
        view.anchors={key:value for key,value in view.anchors.items() if key in anchors}
        check_deadline(deadline)
        return view.finish()
    except (AuthorityReadError,InstrumentMathError,ValueError) as error:
        reason=str(error)
        disposition='resource_limit' if 'resource_limit' in reason else 'unavailable'
        return InstrumentAuthorityResult(request,revision.generation,dispositions=(AuthorityDisposition(request.view,disposition,reason=reason[:2048]),))
