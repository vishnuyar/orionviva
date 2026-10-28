"""Bounded authenticated index of delivered allocation-answer selection manifests."""
import json
from ..allocation_continuation import SelectionManifest
from ..instrument_claims import bounded_id

MAX_ANSWERS=8
MAX_MANIFEST_BYTES=20000


def create_tables(connection):
    connection.execute("CREATE TABLE delivered_allocation_answers(source_sequence INTEGER PRIMARY KEY REFERENCES applied_events(sequence) DEFERRABLE INITIALLY DEFERRED,turn_id TEXT NOT NULL,answer_id TEXT NOT NULL UNIQUE,manifest_json TEXT NOT NULL)")
    connection.execute("CREATE INDEX delivered_allocation_by_anchor ON delivered_allocation_answers(turn_id,answer_id)")


def materialize_delivered(connection,entry):
    if entry.event.event_type!='ConversationTurnSettled':return
    body=entry.event.to_dict()['body'];answer=body.get('answer')
    if type(answer) is not dict or answer.get('answered') is not True or body.get('outcome')!='completed':return
    records=answer.get('allocation_selection_manifest')
    if records is None:return
    try:
        if type(records) is not list or not 1<=len(records)<=4:raise ValueError('invalid saved allocation count')
        manifests=tuple(SelectionManifest.from_dict(m) for m in records)
        turn_id=bounded_id(body.get('turn_id'),'saved turn');answer_id=bounded_id(answer.get('answer_id'),'saved answer')
        if any(m.turn_id!=turn_id or m.answer_id!=answer_id for m in manifests):raise ValueError('saved selection anchor mismatch')
        encoded=json.dumps(records,sort_keys=True,separators=(',',':'),ensure_ascii=False)
        if len(encoded.encode('utf-8'))>MAX_MANIFEST_BYTES:raise ValueError('saved manifest exceeds bound')
    except (ValueError,TypeError):
        # Historical or malformed selection metadata never becomes recovery authority.
        return
    connection.execute('INSERT INTO delivered_allocation_answers VALUES(?,?,?,?)',(entry.sequence,turn_id,answer_id,encoded))
    connection.execute('DELETE FROM delivered_allocation_answers WHERE source_sequence NOT IN (SELECT source_sequence FROM delivered_allocation_answers ORDER BY source_sequence DESC LIMIT ?)',(MAX_ANSWERS,))


def load_selection(revision,turn_id,answer_id):
    from .store import ReadStoreError
    bounded_id(turn_id,'saved turn');bounded_id(answer_id,'saved answer')
    if revision._closed:raise ReadStoreError('closed allocation recovery revision')
    rows=revision.connection.execute('SELECT CASE WHEN length(CAST(manifest_json AS BLOB))<=? THEN manifest_json END FROM delivered_allocation_answers WHERE turn_id=? AND answer_id=? LIMIT 2',(MAX_MANIFEST_BYTES,turn_id,answer_id)).fetchall()
    if len(rows)!=1:return None
    if type(rows[0][0]) is not str:raise ReadStoreError('saved allocation manifest exceeds byte bound')
    try:
        records=json.loads(rows[0][0])
        if type(records) is not list or not 1<=len(records)<=4:raise ValueError('invalid saved selection count')
        result=tuple(SelectionManifest.from_dict(m) for m in records)
        if any(m.turn_id!=turn_id or m.answer_id!=answer_id for m in result):raise ValueError('saved selection anchor mismatch')
        return result
    except (ValueError,TypeError,KeyError) as error:raise ReadStoreError('invalid saved allocation manifest') from error
