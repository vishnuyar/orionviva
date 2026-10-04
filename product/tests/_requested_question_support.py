"""Explicitly requested legacy structured editors, outside the default queue."""
from decimal import Decimal
from viva import questions
from viva.persona import say
from viva.env import jurisdiction_from_env


def _requested_questions(source, limit=questions.DEFAULT_LIMIT, as_of='', jurisdiction='', locale='', _pending=False):
    proj = getattr(source, 'projection', lambda: source)()
    as_of = as_of or '2026-10-04'
    locale = locale or questions._locale()
    groups = (questions._held_questions(proj, locale), questions._transfer_questions(proj, locale),
              questions._merchant_questions(proj, locale), questions._nature_questions(proj, locale),
              questions._rhythm_questions(proj, locale), questions._corroboration_questions(proj, locale),
              questions._expectation_questions(proj, as_of, jurisdiction or jurisdiction_from_env().upper(), locale),
              questions._interview_questions(proj, jurisdiction or jurisdiction_from_env().upper()))
    qs = [q for group in groups for q in group]
    opened, pending = questions._split_declined(proj, qs)
    if _pending:
        return {"questions": [q.to_dict() for q in sorted(pending, key=lambda q: (-q.amount, q.id))], "total": len(pending)}
    opened.sort(key=lambda q: (-q.amount, q.id))
    shown, rest = (opened, []) if limit is None else (opened[:limit], opened[limit:])
    return {'questions': [q.to_dict() for q in shown], 'total': len(opened),
            'tail': {'count': len(rest), 'amount': str(sum((q.amount for q in rest), Decimal('0')))},
            'pending': {'count': len(pending)}, 'invite': say('free_text_invite'),
            'answered_by_document': say('answered_by_document')}


def _requested_pending_questions(source, **kwargs):
    return _requested_questions(source, limit=None, _pending=True, **kwargs)


def _requested_sql_questions(revision, *, as_of, jurisdiction='', locale='', limit=10):
    """Exercise explicitly requested normalized editors without changing public reads."""
    from viva.read_store import questions as sql
    connection = revision.connection
    if not jurisdiction:
        jurisdiction = jurisdiction_from_env().upper()
    generated = sql.candidates(connection, as_of=as_of, locale=locale)
    generated += sql._corroboration_questions(connection, locale=locale)
    generated += sql._expectation_questions(connection, as_of=as_of,
                                            jurisdiction=jurisdiction, locale=locale)
    interview_ids = sql._interview_possible_ids(connection, jurisdiction)
    identities = sql._bounded_candidate_identities(generated, interview_ids)
    decisions = sql._latest_decisions(connection, 'QuestionDeclined', identities)
    generated += sql._interview_questions(connection, jurisdiction=jurisdiction,
                                          locale=locale, declined=decisions)
    opened, pending = [], []
    for question in generated:
        decision = decisions.get(question['id'])
        is_declined = (decision is not None and decision.get('amount') == question['amount']
                       and int(decision.get('count', 0)) == question['count'])
        (pending if is_declined else opened).append(question)
    opened.sort(key=lambda q: (-Decimal(q['amount']), q['id']))
    shown, rest = (opened, []) if limit is None else (opened[:limit], opened[limit:])
    return {'questions': shown, 'total': len(opened),
            'tail': {'count': len(rest), 'amount': str(sum((Decimal(q['amount']) for q in rest), Decimal(0)))},
            'pending': {'count': len(pending)}, 'invite': say('free_text_invite'),
            'answered_by_document': say('answered_by_document')}
