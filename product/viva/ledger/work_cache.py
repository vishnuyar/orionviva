"""Bounded owner-held work reuse, active only inside a canonical operation.

Entries contain immutable derived proofs, never projections or credentials.
Exact input identity checks remain the caller's responsibility on every use.
"""
from collections import OrderedDict
from contextlib import contextmanager
from contextvars import ContextVar
from threading import RLock


_active_memo = ContextVar('ledger_validation_memo', default=None)


class ValidationMemo:
    def __init__(self, capacity=512):
        self._capacity = capacity
        self._entries = OrderedDict()
        self._lock = RLock()

    def get(self, namespace, key):
        with self._lock:
            held = self._entries.get((namespace, key))
            if held is not None:
                self._entries.move_to_end((namespace, key))
            return held

    def put(self, namespace, key, value):
        with self._lock:
            self._entries[(namespace, key)] = value
            self._entries.move_to_end((namespace, key))
            while len(self._entries) > self._capacity:
                self._entries.popitem(last=False)

    def clear(self):
        with self._lock:
            self._entries.clear()


def active_memo():
    return _active_memo.get()


@contextmanager
def memo_scope(memo):
    token = _active_memo.set(memo)
    try:
        yield
    finally:
        _active_memo.reset(token)


@contextmanager
def publication_memo_scope():
    """Reuse an enclosing operation, or own one disposable publication memo."""
    inherited = active_memo()
    if inherited is not None:
        yield inherited
        return
    memo = ValidationMemo()
    with memo_scope(memo):
        try:
            yield memo
        finally:
            memo.clear()
