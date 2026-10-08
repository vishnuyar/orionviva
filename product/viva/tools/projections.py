"""Read-only presentations of existing local projection authorities."""
import datetime
import json
import re
from dataclasses import asdict
from decimal import Decimal
from collections import Counter
from .registry import _validate
from .envelope import ToolResult, figure, refusal, bounded, HYPOTHETICAL, ACTIVITY
from .. import quantity
from ..ledger.events import ISSUED
from ..ledger.projection.measurements import accepted_closings
from ..ledger.projection import goals as goals_view
from .ledger_common import _identifiers

PROJECTION_PARAMS={'type':'object','additionalProperties':False,'properties':{
    'view':{'type':'string','enum':['known_remainder','upcoming_obligations','goal_progress']},
    'currency':{'type':'string','minLength':1},'horizon_days':{'type':'string','pattern':'^[0-9]{1,3}$'}},'required':['view']}

_UNKNOWN_LIMIT='An additional recorded input limitation applies; review the underlying records.'
_LIMIT_COPY={
    'balance_freshness_unconfirmed':'Starting balances were measured before the read date; their freshness is unconfirmed.',
    'balance_conflicted':'The recorded balance disagrees with the transaction reconciliation.',
    'balance_undated':'A starting balance has no measurement date.',
    'income_interrupted':'An incoming pattern has interruptions in the recorded history.',
    'measured_not_confirmed':'The cadence was measured from history and has not been confirmed by you.',
    'observed_prior_only':'Only prior observations support this expectation.',
}
_STATUS_COPY={
    'complete':'complete','paused':'paused','at_risk':'at risk of missing the recorded target',
    'unscheduled':'without a scheduled contribution','on_track':'on track under the recorded plan',
    'ahead':'ahead under the recorded plan',
}
_BASIS_COPY={'confirmed':'confirmed by you','measured':'measured from history','observed':'prior observations only'}


def _limits(codes):
    messages=[]
    for code in codes:
        if code.startswith('release_exceeds_reserved:'):
            parts=code[len('release_exceeds_reserved:'):].rsplit(':',1)
            complete=len(parts)==2 and all(part.strip() for part in parts)
            messages.append('A recorded release exceeded the reserved funds.' if complete else _UNKNOWN_LIMIT)
        else:
            messages.append(_LIMIT_COPY.get(code,_UNKNOWN_LIMIT))
    return ' '.join(dict.fromkeys(messages)) if messages else 'No additional input limitation is recorded.'


def _json(value):
    if isinstance(value,Decimal): return str(value)
    if isinstance(value,dict): return {key:_json(item) for key,item in value.items()}
    if isinstance(value,(tuple,list)): return [_json(item) for item in value]
    return value


def _compatible_starts(proj, currency):
    """The unchanged current-period helper must use accepted cash sources."""
    for account, state in proj.core._acct.items():
        if (not state.seen or state.kind != 'depository' or state.origin != ISSUED
                or not state.currency or (currency and state.currency != currency)):
            continue
        rows = accepted_closings(proj.core, account)
        if not rows:
            return False
        source = rows[-1]
        answer = proj.balance(account)
        if (source.context_conflict or source.kind != 'depository'
                or source.currency != state.currency or answer.currency != source.currency
                or answer.amount != source.amount or answer.dated[:10] != source.dated
                or answer.provenance.doc_id != source.doc_id):
            return False
    return True


def _remainder_data(result, rows):
    """Lossless exclusions: slice indices refer to the shared exclusions list."""
    data = _json(asdict(result))
    data['slices'] = []
    data['exclusion_encoding'] = 'Each slice exclusion_refs indexes the top-level exclusions list.'
    for row in rows:
        item = _json(asdict(row))
        item['exclusion_refs'] = [result.exclusions.index(exclusion) for exclusion in row.exclusions]
        del item['exclusions']
        data['slices'].append(item)
    return data


def _local_goal_inputs(proj, row, day, end, goals):
    """Source only the local terms the unchanged helper actually includes."""
    if not row.steps or row.steps[0].kind != 'balance':
        raise ValueError('missing starting account scope')
    starting=set(row.steps[0].account_ids)
    for account in starting:
        state=proj.core._acct.get(account)
        if (state is None or not state.seen or state.kind != 'depository'
                or state.origin != ISSUED or state.currency != row.currency):
            raise ValueError('incompatible starting account scope')
    inputs=[]; sources=set(); reserved=Decimal('0'); contributions=Decimal('0'); occurrences=[]
    for goal in goals:
        reservations=[{'account_id':account,'amount':str(amount),'currency':row.currency}
                      for account,amount in goal.reservations if account in starting and amount != 0]
        scheduled=[]
        if (goal.currency == row.currency and not goal.issues and goal.state == 'active'
                and goal.monthly_contribution is not None and goal.contribution_day is not None
                and goal.remaining):
            remaining=goal.remaining
            for occurrence in goals_view.contribution_dates(day,goal.contribution_day,through=end):
                amount=min(goal.monthly_contribution,remaining)
                scheduled.append({'date':occurrence,'amount':str(amount),'currency':goal.currency})
                occurrences.append((occurrence,amount,amount))
                contributions+=amount
                remaining-=amount
                if not remaining: break
        if not reservations and not scheduled: continue
        if (not goal.event_ids or any(not isinstance(source,str) or not source.strip()
                                      for source in goal.event_ids)):
            raise ValueError('missing local goal lineage')
        ids=sorted(set(goal.event_ids)); sources.update(ids)
        reserved+=sum((Decimal(item['amount']) for item in reservations),Decimal('0'))
        inputs.append({'goal_id':goal.goal_id,'record_ids':ids,
                       'reservations':reservations,'contributions':scheduled})
    held=[(step.date,step.amount_min,step.amount_max) for step in row.steps if step.kind == 'goal']
    if (reserved != row.reserved_for_goals or contributions != row.goal_contributions
            or Counter(occurrences) != Counter(held)):
        raise ValueError('inconsistent local goal participation')
    return inputs,sources


def read_financial_projections(proj,args,locale='',today=''):
    tool='read_financial_projections'
    errors=_validate(PROJECTION_PARAMS,args) if isinstance(args,dict) else ['Arguments must be an object.']
    if errors: return refusal(tool,'invalid_arguments','; '.join(errors))
    if args.get('currency') is not None and not args['currency'].strip(): return refusal(tool,'invalid_arguments','Currency cannot be blank.')
    if args['view']=='goal_progress' and 'horizon_days' in args: return refusal(tool,'invalid_arguments','Goal progress does not accept a horizon.')
    horizon=args.get('horizon_days','30')
    if not isinstance(horizon,str) or not re.fullmatch(r'[0-9]{1,3}',horizon) or not 1<=int(horizon)<=366:
        return refusal(tool,'invalid_arguments','The horizon must be an integer decimal string from one to three hundred sixty-six.')
    try:
        day=datetime.date.fromisoformat(today) if today else datetime.date.today()
        if today and day.isoformat()!=today: raise ValueError
        end=(day+datetime.timedelta(days=int(horizon))).isoformat()
    except (ValueError,TypeError,OverflowError): return refusal(tool,'bad_date','Use an ISO read date.')
    currency=args.get('currency'); figures=[]; records=set(); accounts=set(); caveats=[]; data={}
    if args['view']=='known_remainder':
        if not _compatible_starts(proj, currency):
            return refusal(tool,'projection_start_unavailable','The existing starting balance is not compatible with an accepted cash source.')
        result=proj.current_period(day.isoformat(),int(horizon))
        rows=[row for row in result.slices if not currency or row.currency==currency]
        if not rows: return refusal(tool,result.refusal_reason or 'no_eligible_liquid_balance','No eligible starting currency balance is held.')
        data=_remainder_data(result, rows)
        goals=goals_view.goals(proj.core,day.isoformat())
        for index,row in enumerate(rows):
            try:
                local_inputs,local_sources=_local_goal_inputs(proj,row,day.isoformat(),end,goals)
            except ValueError:
                return refusal(tool,'projection_goal_sources_unavailable','These recorded goal inputs do not have complete local source records. They cannot support this projection.')
            row_sources=sorted(set(row.record_ids)|local_sources)
            data['slices'][index]['local_goal_inputs']=local_inputs
            data['slices'][index]['record_ids']=row_sources
            records.update(row_sources)
            accounts.update(row.account_ids)
            boundary=bounded(whole=False,selected=[{'kind':'account','value':a} for a in row.account_ids])
            for amount,label in [(row.remainder_min,'lower known remainder'),(row.remainder_max,'upper known remainder')]:
                figures.append(figure(amount,label+' — hypothetical endpoint '+end,quantity=quantity.BALANCE,kind=HYPOTHETICAL,currency=row.currency,
                    dated=end,record_ids=row_sources,boundary=boundary))
            caveats.extend(['Historical input grade: '+(row.grade or 'ungraded')+'; measurement dates: '+', '.join(row.evidence_dates)+'.',
                'Historical input balances, local reserves, qualified recurring money and goal contributions retain their existing exclusions and ranges.',
                'Planned discretionary spending is missing. This remainder is not spending permission.',
                'Input limitations: '+_limits(row.caveats)])
        caveats.append('Projection horizon: '+day.isoformat()+' to '+end+'. Expected incoming money is not guaranteed; future amounts and dates are hypothetical.')
        data['record_ids']=sorted(records)
    elif args['view']=='upcoming_obligations':
        rows=[row for row in proj.obligations(day.isoformat()) if day.isoformat()<=row.expected_date<=end and (not currency or row.currency==currency)]
        if not rows: return refusal(tool,'no_upcoming_expectations','No supported next outgoing expectation is held within this horizon.')
        if len(rows)>24: return refusal(tool,'projection_payload_limit','Choose a narrower projection scope.')
        data={'next_expectations':[_json(asdict(row)) for row in rows],'horizon_start':day.isoformat(),'horizon_end':end}
        for row in rows:
            records.update(row.record_ids)
            for amount,label in [(-row.amount_max,'lower expected outgoing cash movement'),(-row.amount_min,'upper expected outgoing cash movement')]:
                figures.append(figure(amount,label+' — '+row.subject+' — expected '+row.expected_date,quantity=quantity.MOVEMENT,kind=HYPOTHETICAL,
                    currency=row.currency,dated=row.expected_date,record_ids=row.record_ids,
                    boundary=bounded(whole=False,selected=[{'kind':'merchant','value':row.subject}])))
            caveats.append(row.subject+': historical basis '+_BASIS_COPY.get(row.basis,_UNKNOWN_LIMIT)+', input grade '+(row.grade or 'ungraded')+', observed '+row.dated_from+' to '+row.dated_to+'; '+_limits(row.caveats))
        caveats.append('Only each held next expectation within the horizon is shown. This is not a full payment calendar; further occurrences are not generated. Dates and amounts are hypothetical expectations, not contractual due dates.')
    else:
        rows=[row for row in proj.goals(day.isoformat()) if not currency or row.currency==currency]
        if not rows: return refusal(tool,'no_recorded_goals','No local goal is recorded in this scope.')
        if len(rows)>8: return refusal(tool,'goal_progress_payload_limit','Choose one currency to bound the goal response.')
        data={'goals':[_json(asdict(row)) for row in rows]}
        for row in rows:
            records.update(row.event_ids)
            values=[(row.target_amount,'recorded local target',ACTIVITY),
                    (row.reserved,'recorded local reservation',ACTIVITY),
                    (row.remaining,'remaining local goal amount',HYPOTHETICAL),
                    (row.monthly_contribution,'recorded monthly contribution plan',ACTIVITY),
                    (row.required_monthly,'required monthly contribution estimate',HYPOTHETICAL)]
            for amount,label,kind in values:
                if amount is not None:
                    figures.append(figure(amount,label+' — '+row.title,quantity=quantity.BALANCE,kind=kind,
                        currency=row.currency,record_ids=row.event_ids,boundary=bounded(whole=False)))
            status=_STATUS_COPY.get(row.status,_UNKNOWN_LIMIT)
            caveats.append(row.title+': recorded local plan and reserves, not a bank transfer; '+status+('' if status.endswith('.') else '.'))
            if row.projected_completion_date: caveats.append(row.title+': hypothetical completion '+row.projected_completion_date+'.')
            if row.next_contribution_date: caveats.append(row.title+': next planned contribution '+row.next_contribution_date+'.')
            if row.target_date: caveats.append(row.title+': recorded target date '+row.target_date+'.')
            if row.issues: caveats.append(row.title+': '+_limits(row.issues))
        caveats.append('Local activity terms carry no bank evidence grade. Contribution and completion estimates are hypothetical; existing available-account exclusions and stale measurements remain in the inputs.')
    result=ToolResult(tool=tool,ok=True,data=data,figures=figures,identifiers=_identifiers(proj,accounts),record_ids=sorted(records),caveats=caveats,
        text='Existing local projections with their assumptions and historical inputs.')
    if len(figures)>50 or len(json.dumps(result.to_dict()).encode())>10_000:
        return refusal(tool,'goal_progress_payload_limit' if args['view']=='goal_progress' else 'projection_payload_limit',
                       'The complete projection does not fit in one bounded answer.')
    return result
