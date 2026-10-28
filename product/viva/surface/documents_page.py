"""Compose bounded Documents data at the public surface boundary."""
import json
import time
from ..persona import moment
from ..read_store.documents_page import DocumentsPageError, MAX_RESPONSE_BYTES, MAX_SECONDS
from .documents import _contribution, _reading_sentence


def compose_documents_page(data, *, locale='', reading_configured=False, started):
    """Retain the indexed read's budget through final public composition."""
    def document(item):
        result = dict(item)
        contribution = result.pop('contribution_data', {})
        attention = result.pop('snapshot_attention', '')
        if 'snapshot_status' in result:
            result['snapshot_sentence'] = (
                'Accepted source sections are retained; other sections need review.' if attention == 'partial'
                else 'Some source sections remain unresolved.' if attention == 'unresolved'
                else moment('documents_snapshot_' + result['snapshot_status']))
            result['activity_sentence'] = moment('documents_activity_' + result['activity_status'])
            result['contribution'] = _contribution(result['id'], contribution, locale)
        return result
    result = dict(data)
    result['documents'] = [document(item) for item in data['documents']]
    selection = dict(data['selected_document'])
    if selection['state'] == 'ready':
        selection['document'] = document(selection['document'])
    result['selected_document'] = selection
    counts = data['summary']['counts']
    result['reading_sentence'] = _reading_sentence(
        [{'reading': 'never_read'}] if counts and counts['never_read'] else
        [{'reading': 'read_yielded_nothing'}] if counts and counts['read_yielded_nothing'] else [], reading_configured) if counts else ''
    def size():
        return len(json.dumps(result, separators=(',', ':'), sort_keys=True).encode('utf-8'))
    if selection['state'] == 'ready' and size() > MAX_RESPONSE_BYTES:
        result['selected_document'] = {'state': 'unavailable', 'reason': 'detail_resource_limit', 'document': None}
    if size() > MAX_RESPONSE_BYTES or time.monotonic() - started > MAX_SECONDS:
        raise DocumentsPageError('resource_limit')
    return result
