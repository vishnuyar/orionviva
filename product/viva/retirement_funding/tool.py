"""Current-run sealed retirement-funding receipts with complete serialized bounds."""
import json
from time import monotonic
from viva.investment.contracts import EvidenceError, ResourceLimit, day, digest
from viva.investment.authority import check
from viva.tools.envelope import ToolResult, figure, bounded, refusal
from viva.tools.registry import ToolSpec
from viva.instrument_evidence import _attest_figure, _attest_assertion
from .contracts import TOOL, ANNUAL, ROLLOVERS, Request, NUMERIC_CLAIMS, ASSERTION_CLAIMS
from .sql import read_sql

class RetirementToolResult(ToolResult):
    def to_dict(self):
        out=super().to_dict()
        out['provenance']=[{'source_anchor_pool':'data.lineage.anchors'}]
        for emitted,source in zip(out['figures'],self.figures):
            for key in ('subject','association_id','source_lineage_digest','authority_record_id','direction'):
                emitted[key]=source[key]
        return out

_STRING = {'type': 'string', 'minLength': 1}
_PLANS = {'type': 'array', 'items': _STRING, 'minItems': 1, 'maxItems': 3, 'uniqueItems': True}
PARAMS = {'oneOf': [{'type': 'object', 'additionalProperties': False, 'properties': {'view': {'const': view}, 'plans': _PLANS, 'currency': _STRING, **extra}, 'required': ['view', 'plans', 'currency', *extra]} for view, extra in ((ANNUAL, {'year': {'type': 'integer', 'minimum': 1, 'maximum': 9998}}), (ROLLOVERS, {'from': {'type': 'string', 'format': 'date'}, 'to': {'type': 'string', 'format': 'date'}}))]}


def result(connection, frontier, args, run_token, today, *, deadline=None, read_evidence=None):
    deadline = min(deadline, monotonic() + 2) if deadline is not None else monotonic() + 2
    try:
        request = Request.from_dict(args); day(today)
        if request.ending > today:
            raise EvidenceError('selected retirement date exceeds runtime horizon')
        raw = read_evidence(request, deadline) if read_evidence is not None else read_sql(connection, frontier, request, deadline)
        lineage = raw['lineage']; record_ids = sorted({anchor[0] for anchor in lineage['anchors']})
        provenance = [{'doc_id': anchor[0], 'page': anchor[1]} for anchor in lineage['anchors'] if anchor[1] is not None]
        from .lineage import index_ranges
        population=[{**{k:v for k,v in item.items() if k!='source_occurrences'},'source_occurrence_ranges':index_ranges(item['source_occurrences'])} for item in raw['population']]
        source_data={'view':request.view,'subject':request.subject,'lineage':lineage,'payroll_population':population,'excluded':raw['excluded'],'source_scope':'accepted recorded payroll population' if request.view==ANNUAL else 'complete accepted posting set for each documented direct rollover','figure_sources':{item['id']:{'source_occurrence_ranges':index_ranges(item['source_occurrences']),'association_id':item['association_id']} for item in raw['figures']}}
        source_digest=digest(source_data)
        source_data['source_lineage_digest']=source_digest
        from .lineage import decode_pool
        source_occurrences,_=decode_pool(lineage)
        figures = []
        for item in raw['figures']:
            selected = [{'kind': 'account_set', 'value': json.dumps(sorted(request.plans),separators=(',',':'))}]
            cut = [*selected, {'kind': 'period', 'value': item['from'], 'to': item['to']}]
            figure_records=sorted({source_occurrences[index]['field'].document for index in item['source_occurrences']})
            plain = figure(item['value'], item['label'], quantity=item['quantity'], currency=item['currency'], grade=item['grade'], record_ids=figure_records, boundary=bounded(whole=False, selected=selected, cut=cut), subject=item['subject'])
            plain.update(association_id=item['association_id'], source_occurrences=item['source_occurrences'], source_lineage_digest=source_digest, authority_record_id=item['id'], direction=item['direction'])
            figures.append(_attest_figure(plain, item['claim'], run_token=run_token))
        assertions = []
        for item in raw['assertions']:
            field = item['field']; contract = ASSERTION_CLAIMS[item['claim']]
            assertions.append(_attest_assertion({'claim': item['claim'], 'value': item['value'], 'value_type': 'date' if contract == 'instrument_date' else 'literal_text', 'account': request.subject_id, 'anchors': [{'document_id': field.document, 'page': field.page}], 'observation_ids': [item['association_id']], 'record_association': item['association_id'], 'grade': field.grade, 'disposition': 'accepted', 'source_lineage_digest': source_digest,'association_label':item['association_label'],'source_account_id':item['source_account_id'],'destination_account_id':item['destination_account_id']}, run_token=run_token))
        output = RetirementToolResult(TOOL, True, figures=figures, record_ids=record_ids, provenance=provenance, data=source_data, instrument_assertions=assertions)
        if len(json.dumps(output.to_dict(), ensure_ascii=False, separators=(',', ':')).encode()) > 32000:
            raise ResourceLimit('complete retirement tool envelope byte bound')
        check(deadline)
        return output
    except ResourceLimit:
        return refusal(TOOL, 'resource_limit', 'The complete retirement funding evidence exceeds its read bound.')
    except (EvidenceError, ValueError, TypeError, KeyError):
        return refusal(TOOL, 'retirement_funding_unavailable', 'Complete accepted retirement funding evidence is unavailable.')


def spec(connection, frontier, run_token, today):
    return ToolSpec(TOOL, PARAMS, lambda args: result(connection, frontier, args, run_token, today), emits={'reference_kinds': ['figure', 'read_figures', 'instrument_date', 'instrument_text'], 'quantities': sorted(set(NUMERIC_CLAIMS.values())), 'entity_kinds': []}, bounds={'max_payload_bytes': 32000, 'max_figures': 64, 'max_execution_ms': 2000, 'max_statements': 120, 'max_rows': 1000, 'max_anchors': 512})


def runtime_spec(runtime, today):
    item = spec(None, None, None, today)
    def invoke(args):
        from viva.investment.events import LockedEventPrefix
        if runtime is None or runtime.revision is None:
            return refusal(TOOL, 'current_data_unavailable', 'Current authenticated retirement records are unavailable.')
        revision = runtime.revision
        def authenticated(request, deadline):
            store = revision._store; identity = store.authenticated_source_identity(revision)
            if revision.connection.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='investment_evidence_authenticated_source'").fetchone() is None:raise EvidenceError('authenticated retirement projection unavailable')
            row = revision.connection.execute('SELECT source_count,source_head FROM investment_evidence_authenticated_source WHERE singleton=1').fetchone()
            if row != (identity['count'], identity['head']):
                raise EvidenceError('retirement read does not belong to authenticated source revision')
            frontier_row = revision.connection.execute('SELECT event_count,last_event_id,prefix_digest FROM retirement_funding_frontier WHERE singleton=1').fetchone()
            if frontier_row is None or frontier_row[0] != identity['count']:
                raise EvidenceError('retirement authenticated frontier unavailable')
            raw = read_sql(revision.connection, LockedEventPrefix(*frontier_row), request, deadline)
            store.authenticated_source_identity(revision)
            return raw
        return result(None, None, args, runtime.run_token, today, deadline=runtime.deadline, read_evidence=authenticated)
    item.fn = invoke
    return item
