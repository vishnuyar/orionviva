"""Bounded employee-only and paired-record calculations over authenticated sources."""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, localcontext
from viva.investment.contracts import EvidenceError, ResourceLimit, digest, encode, Field
from viva.investment.events import accepted
from viva.investment.payroll import _financial_identity, source_fields, _complete
from viva.investment.authority import check
from .contracts import ANNUAL, NUMERIC_CLAIMS
from .population import decode
from .lineage import Pool
from .posting_closure import totals


def _covered(periods, start, end):
    cursor = date.fromisoformat(start); finish = date.fromisoformat(end)
    for left, right in sorted(periods):
        left = date.fromisoformat(left); right = date.fromisoformat(right)
        if left > cursor:
            return False
        if right >= cursor:
            cursor = right + timedelta(days=1)
    return cursor > finish


def _rows(statements, request):
    values = []
    for statement in statements:
        if (request.view!=ANNUAL and statement.account.value not in request.plans) or statement.currency.value != request.currency or not statement.disposition.startswith('accepted_complete'):
            raise EvidenceError('selected plan statement unavailable')
        for row in statement.rows:
            if request.beginning <= row.date.value <= request.ending:
                values.append((statement, row))
    if len(statements) > 120 or len(values) > 1000:
        raise ResourceLimit('retirement statement/occurrence bound')
    return values


def read(statements, population, witnesses, closures, request, deadline, *, membership=()):
    check(deadline)
    pool = Pool(); figures = []; assertions = []; manifest = []; excluded = []
    rows = _rows(statements, request)
    if {source.account.value for source in membership}!=set(request.plans):
        raise EvidenceError('selected retirement plan membership unavailable')
    membership_uses=[]
    for source in membership:
        candidate=next((row for row in source.rows if row.funding_status=='accepted' and getattr(row.funding_witness,'payroll_dependency',None) is not None),None)
        if candidate is None:raise EvidenceError('retirement source membership unavailable')
        dependency=candidate.funding_witness.payroll_dependency
        membership_uses.extend(pool.add(source.account,source.observation_id,'/account'))
        membership_uses.extend(pool.add(dependency.source.deductions[dependency.ordinal],dependency.source_event_id,'/deductions/'+str(dependency.ordinal)))
        pool.dependency(dependency.source_event_id,dependency.source_body_digest,'retirement_plan_membership',{'plan':source.account.value,'occurrence':dependency.occurrence_id})
    def emit(claim, amount, identity, uses, *, relationship='', direction='', members=None):
        check(deadline)
        if len(figures) >= 64:
            raise ResourceLimit('retirement figure bound')
        figures.append({'id': digest((claim, identity, request.subject_id, request.beginning, request.ending, request.currency)),
                        'claim': claim, 'quantity': NUMERIC_CLAIMS[claim], 'value': str(amount),
                        'label': claim.replace('_', ' '), 'currency': request.currency,
                        'grade': 'unverified', 'subject': {**request.subject,**({'relationship_id':relationship} if relationship else {})},
                        'association_id': relationship, 'source_occurrences': sorted(set((*membership_uses,*uses))),
                        'from': request.beginning, 'to': request.ending, 'direction': direction,
                        'member_ids': sorted(members or request.plans)})
    if request.view == ANNUAL:
        selected = []; canonical = {}; periods = []; row_uses = {}
        for record in population:
            check(deadline)
            if record['population'] is None:
                raise EvidenceError('recorded payroll source year or disposition unresolved')
            source = decode(record['population']); economic = source.source
            start, end = source.period_start, source.period_end
            # Missing edges are not excluded just because the printed pay date
            # appears outside the selected year: their coverage is unknown.
            if source.version != 'payroll-source-v2' or start is None or end is None or not accepted(start, end):
                raise EvidenceError('recorded payroll period unavailable')
            relevant = start.value <= request.ending and end.value >= request.beginning or request.beginning <= economic.pay_date.value <= request.ending
            if not relevant:
                continue
            if record['status'] != 'accepted' or source.disposition != 'accepted' or not _complete(economic):
                raise EvidenceError('selected recorded payroll population held')
            if economic.currency.value != request.currency:
                raise EvidenceError('recorded employee source currency differs')
            uses = pool.add(source, record['id'])
            population_dependency=pool.dependency(record['id'], record['digest'], 'payroll_population', {'reading_id': source.reading_id, 'reading_digest': source.reading_digest})
            manifest.append({'population_dependency':population_dependency,'payroll_source': economic.source_reference.value, 'status': source.disposition, 'source_occurrences': uses})
            identity = (_financial_identity(economic), start.value, end.value)
            ref = (economic.source_reference.value,economic.pay_date.value)
            if ref in canonical and canonical[ref][0] != identity:
                raise EvidenceError('conflicting recorded payroll copies')
            if ref in canonical:
                canonical[ref][1].append((record, source, uses)); continue
            copies = [(record, source, uses)]; canonical[ref] = (identity, copies)
            selected.append((economic, copies)); periods.append((start.value, end.value))
        if not selected or not _covered(periods, request.beginning, request.ending):
            raise EvidenceError('recorded payroll population does not cover selected year')
        total = Decimal(0); subtotals = {plan: Decimal(0) for plan in request.plans}; all_uses = []; occurrences = set(); counted_rows = set()
        for economic, copies in selected:
            check(deadline)
            all_uses.extend(use for _, _, uses in copies for use in uses)
            for occurrence in economic.deductions:
                if occurrence.category.value != 'retirement' or not request.beginning <= economic.pay_date.value <= request.ending:
                    continue
                identity = (economic.source_reference.value, economic.pay_date.value, occurrence.ordinal, occurrence.contribution_reference.value)
                if identity in occurrences:
                    raise EvidenceError('employee occurrence reused')
                occurrences.add(identity)
                matches = []
                for statement, row in rows:
                    dependency = getattr(row.funding_witness, 'payroll_dependency', None)
                    if dependency is None or row.kind.value != 'contribution':
                        continue
                    if dependency.source.source_reference.value == economic.source_reference.value and dependency.source.pay_date.value == economic.pay_date.value and dependency.ordinal == occurrence.ordinal:
                        matches.append((statement, row, dependency))
                # Equivalent complete plan copies corroborate the same cash event.
                by_cash = defaultdict(list)
                for statement, row, dependency in matches:
                    by_cash[row.cash_event_id].append((statement, row, dependency))
                if len(by_cash) != 1:
                    raise EvidenceError('employee deduction has no unique accepted selected-plan row')
                match_copies = next(iter(by_cash.values())); statement, row, dependency = match_copies[0]
                if row.cash_event_id in counted_rows:
                    raise EvidenceError('one plan contribution funds multiple employee occurrences')
                counted_rows.add(row.cash_event_id)
                if row.funding_status != 'accepted' or row.funding_role != 'external_party' or _financial_identity(dependency.source) != _financial_identity(economic) or witnesses.get(dependency.source_event_id) != (dependency.source_body_digest, False):
                    raise EvidenceError('accepted current payroll plan witness unavailable')
                if row.amount.value != occurrence.amount.value and Decimal(row.amount.value) != Decimal(occurrence.amount.value):
                    raise EvidenceError('employee contribution magnitude differs')
                if row.date.value != economic.pay_date.value or statement.currency.value != economic.currency.value or row.funding_reference.value != occurrence.contribution_reference.value:
                    raise EvidenceError('employee contribution date/reference differs')
                for copy_statement, copy_row, copy_dependency in match_copies:
                    all_uses.extend(pool.add(copy_statement.account, copy_statement.observation_id, '/account'))
                    all_uses.extend(pool.add(copy_statement.currency, copy_statement.observation_id, '/currency'))
                    all_uses.extend(pool.add(copy_statement.start, copy_statement.observation_id, '/start'))
                    all_uses.extend(pool.add(copy_statement.end, copy_statement.observation_id, '/end'))
                    all_uses.extend(pool.add(copy_row, copy_statement.observation_id, '/rows/' + str(copy_row.ordinal)))
                    pool.dependency(copy_row.cash_event_id, copy_row.cash_body_digest, 'plan_cash', {'plan': copy_statement.account.value, 'row': copy_row.observation_id})
                    pool.dependency(copy_dependency.source_event_id, copy_dependency.source_body_digest, 'payroll_witness', {'decomposition_event_id': copy_dependency.decomposition_event_id, 'decomposition_digest': copy_dependency.decomposition_body_digest, 'net_deposit_event_id': copy_dependency.net_deposit_event_id, 'net_deposit_digest': copy_dependency.net_deposit_body_digest, 'net_movement_key': copy_dependency.net_movement_key,'occurrence_id':copy_dependency.occurrence_id,'ordinal':copy_dependency.ordinal,'payroll_identity':copy_dependency.payroll_identity,'currency':copy_dependency.currency,'corroborating_sources':[[copy.source_event_id,copy.source_body_digest,copy.occurrence_id,copy.ordinal] for copy in copy_dependency.corroborating_sources]})
                if statement.account.value not in request.plans:
                    excluded.append({'payroll_source':economic.source_reference.value,'ordinal':occurrence.ordinal,'destination_account':statement.account.value,'reason':'outside_explicit_selected_set','amount':occurrence.amount.value,'source_occurrences':sorted(set(all_uses))})
                    continue
                with localcontext() as context:
                    context.prec = 128
                    amount = Decimal(occurrence.amount.value); total += amount; subtotals[statement.account.value] += amount
        emit('employee_retirement_contributions', total, request.subject_id, all_uses)
        figures[-1]['label']+=' · '+str(request.year)
        manifest.sort(key=lambda item: item['payroll_source'])
    else:
        selected = {}
        for statement, row in rows:
            witness = row.funding_witness
            if row.kind.value != 'contribution' or row.funding_role != 'retirement_rollover':
                continue
            if row.funding_status != 'accepted' or witness is None or witness.counterpart_account not in request.plans:
                raise EvidenceError('selected rollover counterpart unavailable')
            outgoing = [(s, r) for s, r in rows if s.account.value == witness.counterpart_account and r.cash_event_id == witness.transaction_id]
            if not outgoing:
                raise EvidenceError('opposing accepted rollover source row unavailable')
            source_statement, source_row = outgoing[0]
            if source_row.kind.value != 'withdrawal' or source_row.cash_body_digest != witness.transaction_digest or Decimal(source_row.amount.value) != Decimal(row.amount.value) or source_row.date.value != row.date.value:
                raise EvidenceError('opposing rollover amount/date differs')
            if not accepted(row.funding_reference,source_row.funding_reference,row.counterpart_reference,source_row.counterpart_reference,row.funding_role_source,source_row.funding_role_source) or not row.funding_reference.value or row.funding_reference.value!=source_row.funding_reference.value or row.counterpart_reference.value!=source_statement.account.raw or source_row.counterpart_reference.value!=statement.account.raw or source_row.funding_role_source.value!='retirement_rollover':
                raise EvidenceError('rollover printed relationship reference or endpoint differs')
            key = (source_row.cash_event_id, row.cash_event_id)
            association = 'retirement-rollover:' + digest((source_statement.account.value, statement.account.value, row.funding_role_source.value, row.funding_reference.value, source_row.cash_event_id, row.cash_event_id))
            if key in selected:
                selected[key]['copies'].append((statement, row)); continue
            selected[key] = {'association': association, 'source': (source_statement, source_row), 'destination': (statement, row), 'copies': [(statement, row)]}
        if not selected:
            raise EvidenceError('accepted direct rollover records unavailable')
        if len(selected) > 2:
            raise ResourceLimit('direct rollover association bound')
        for record in selected.values():
            check(deadline)
            association = record['association']; source_statement, source_row = record['source']; statement, row = record['destination']
            uses = []
            for owner_statement, owner_row in [record['source'], *record['copies']]:
                uses.extend(pool.add(owner_statement.account, owner_statement.observation_id, '/account'))
                uses.extend(pool.add(owner_statement.currency, owner_statement.observation_id, '/currency'))
                uses.extend(pool.add(owner_row, owner_statement.observation_id, '/rows/' + str(owner_row.ordinal)))
                witness=owner_row.funding_witness
                if witness is not None:
                    pool.dependency(owner_row.cash_event_id,owner_row.cash_body_digest,'rollover_witness',{'observation_id':owner_row.observation_id,'local_id':owner_row.local_id,'ordinal':owner_row.ordinal,'role':witness.role,'counterpart_account':witness.counterpart_account,'transaction_id':witness.transaction_id,'transaction_digest':witness.transaction_digest,'source_row_event_id':witness.source_row_event_id})
            expected = {source_row.cash_event_id: source_row.cash_body_digest, row.cash_event_id: row.cash_body_digest}
            paired = {identifier: closures[identifier] for identifier in expected if identifier in closures}
            checking, income = totals(paired, expected)
            for identifier, closure in paired.items():
                normalized=dict(closure)
                normalized['dependencies']=[pool.dependency(event['id'],event['digest'],'ledger_event',{'event_type':event['type'],'body':event['body'],'source':event['source']}) for event in closure['dependencies']]
                pool.dependency(identifier, expected[identifier], 'complete_posting_closure', normalized)
            label=source_statement.account.value+' → '+statement.account.value+' · '+row.date.value+' · '+row.funding_reference.value
            for claim, amount, direction in (('direct_rollover_amount', row.amount.value, ''), ('rollover_source_outflow', source_row.amount.value, 'outflow'), ('rollover_destination_inflow', row.amount.value, 'inflow'), ('rollover_checking_receipts', checking, 'inflow'), ('rollover_attributed_income', income, '')):
                if amount is None:continue
                emit(claim, amount, association, uses, relationship=association, direction=direction)
                figures[-1]['label']+=' · '+label
                figures[-1]['subject'].update(source_account_id=source_statement.account.value,destination_account_id=statement.account.value)
            for claim, value, field in (('rollover_date', row.date.value, row.date), ('rollover_reference', row.funding_reference.value, row.funding_reference), ('rollover_source_account', source_statement.account.raw, source_statement.account), ('rollover_destination_account', statement.account.raw, statement.account)):
                assertions.append({'claim': claim, 'value': value, 'field': field, 'association_id': association, 'account': request.subject_id, 'source_occurrences': uses,'association_label':label,'source_account_id':source_statement.account.value,'destination_account_id':statement.account.value})
    check(deadline)
    return {'figures': figures, 'assertions': assertions, 'lineage': pool.to_dict(), 'population': manifest, 'excluded': excluded, 'subject': request.subject, 'view': request.view}
