"""Authenticated Activity continuation within one held normalized revision."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re

from .store import ReadStoreError

MAX_CURSOR_LENGTH = 4096


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode('utf-8')


def _encode(scope, offset, served_focus, secret):
    body = {'scope':scope, 'offset':offset, 'served_focus':served_focus}
    raw = _canonical({'body':body, 'mac':hmac.new(secret, _canonical(body), hashlib.sha256).hexdigest()})
    token = base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=')
    if len(token) > MAX_CURSOR_LENGTH:
        raise ReadStoreError('Activity cursor exceeds its byte bound')
    return token


def _decode(token, scope, secret, *, inherit_focus=False):
    try:
        if (not isinstance(token, str) or not 0 < len(token) <= MAX_CURSOR_LENGTH
                or re.fullmatch(r'[A-Za-z0-9_-]+', token) is None):
            raise ValueError
        raw = base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True)
        envelope = json.loads(raw.decode('utf-8'))
        if not isinstance(envelope, dict) or set(envelope) != {'body','mac'}:
            raise ValueError
        body = envelope['body']
        if (not isinstance(body, dict) or set(body) != {'scope','offset','served_focus'}
                or type(body['offset']) is not int or body['offset'] < 0
                or not isinstance(body['served_focus'], str)
                or not isinstance(envelope['mac'], str)
                or not hmac.compare_digest(envelope['mac'], hmac.new(secret, _canonical(body), hashlib.sha256).hexdigest())
                or _canonical(envelope) != raw
                or base64.urlsafe_b64encode(raw).decode('ascii').rstrip('=') != token):
            raise ValueError
    except Exception:
        raise ReadStoreError('Activity cursor is malformed') from None
    # An omitted continuation focus inherits only the authenticated policy.
    # A caller explicitly changing it still crosses the chain's scope.
    if inherit_focus:
        saved_scope = body['scope']
        if not isinstance(saved_scope, dict) or not isinstance(saved_scope.get('focus'), str):
            raise ReadStoreError('Activity cursor focus is malformed')
        scope = {**scope, 'focus':saved_scope['focus']}
    if body['scope'] != scope:
        raise ReadStoreError('Activity cursor is stale or belongs to another read scope')
    result = body['offset'], body['served_focus']
    return (*result, scope) if inherit_focus else result


def activity_page(revision, projection, *, secret, limit=50, cursor='', focus=None, as_of=''):
    """Count distinct served identities, including an initial focus replacement."""
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ReadStoreError('Activity limit must be between 1 and 100')
    if not isinstance(secret, bytes) or len(secret) < 32:
        raise ValueError('Activity cursors require a private 256-bit key')
    source = revision.connection.execute('SELECT source_count,source_head,publication_epoch '
        'FROM projection_meta WHERE singleton=1').fetchone()
    if source is None:
        raise ReadStoreError('Activity source identity is unavailable')
    identity = {'count':source[0], 'head':source[1], 'epoch':source[2], 'generation':revision.generation}
    scope = {'version':1, 'ordering':1, 'source':identity, 'as_of':as_of, 'limit':limit, 'focus':focus or ''}
    pending = {row['a'] for row in projection.transfer_suggestions()}
    ordered = sorted(projection.movements(), key=lambda m:(m.key in pending, m.date, m.key), reverse=True)
    total = len(ordered)
    if cursor:
        if focus is None:
            offset, served_focus, scope = _decode(cursor, scope, secret, inherit_focus=True)
            focus = scope['focus']
        else:
            offset, served_focus = _decode(cursor, scope, secret)
        if served_focus and (served_focus != focus or not any(m.key == served_focus for m in ordered)):
            raise ReadStoreError('Activity cursor focus is unavailable')
        remaining = [m for m in ordered if m.key != served_focus]
        if offset > len(remaining):
            raise ReadStoreError('Activity cursor offset is unavailable')
        shown = remaining[offset:offset+limit]
        offset += len(shown)
    else:
        shown = ordered[:limit]
        offset, served_focus = len(shown), ''
        focused = next((m for m in ordered if m.key == focus), None) if focus else None
        if focused is not None and all(m.key != focus for m in shown):
            shown = [*shown[:-1], focused]
            offset -= 1
            served_focus = focus
    cumulative = offset + bool(served_focus)
    remaining_count = total - cumulative
    page = {'version':1, 'revision':hashlib.sha256(_canonical({'source':identity,'as_of':as_of})).hexdigest(),
        'next_cursor':_encode(scope, offset, served_focus, secret) if remaining_count else None,
        'cumulative_count':cumulative, 'remaining_count':remaining_count}
    return (shown, total-len(shown)), page
