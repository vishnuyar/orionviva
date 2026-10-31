"""Owned canonical event bytes and exact historical JSON-array proofs.

The index is local to one validation operation. It neither authenticates an
event stream nor replaces the store's physical-chain checks.
"""
from copy import deepcopy
from hashlib import sha256
from weakref import WeakSet
import json
import math

from .contracts import canonical


def _json_primitives(value):
    kind = type(value)
    if value is None or kind in (str, int, bool):
        return True
    if kind is float:
        return math.isfinite(value)
    if kind in (tuple, list):
        return all(_json_primitives(item) for item in value)
    if kind is dict:
        return all(type(key) is str and _json_primitives(item) for key, item in value.items())
    return False


def _encode_event(event):
    wire = event.to_dict()
    if _json_primitives(wire):
        return json.dumps(wire, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=False, allow_nan=False).encode('utf-8')
    return canonical(wire)


class PrefixProofIndex:
    """Detach inputs before deriving every historical prefix in one pass."""

    def __init__(self, events):
        self.__events = deepcopy(tuple(events))
        self.__encoded = tuple(_encode_event(event) for event in self.__events)
        state = sha256(b'[')
        digests = []
        for ordinal in range(len(self.__encoded) + 1):
            if ordinal:
                if ordinal > 1:
                    state.update(b',')
                state.update(self.__encoded[ordinal - 1])
            prefix_state = state.copy()
            prefix_state.update(b']')
            digests.append(prefix_state.hexdigest())
        self.__digests = tuple(digests)
        self.__ids = tuple(event.event_id for event in self.__events)

    @property
    def events(self):
        """Return a detached validation basis without exposing owned bodies."""
        return deepcopy(self.__events)

    def proof(self, count):
        from .events import LockedEventPrefix
        if type(count) is not int or not 0 <= count <= len(self.__ids):
            raise ValueError('event prefix count outside owned snapshot')
        return LockedEventPrefix(count, self.__ids[count - 1] if count else '',
                                 self.__digests[count])


_issued_evidence = WeakSet()


class _OwnedEvidence(PrefixProofIndex):
    """One independently owned history for fixed internal validation work."""

    def __init__(self, events):
        super().__init__(events)
        self.__by_id = {event.event_id: event for event in self._PrefixProofIndex__events}
        _issued_evidence.add(self)

    def __copy__(self):
        raise TypeError('private evidence ownership cannot be copied')

    def __deepcopy__(self, memo):
        raise TypeError('private evidence ownership cannot be copied')

    def _check(self):
        if type(self) is not _OwnedEvidence or self not in _issued_evidence:
            raise TypeError('genuine private evidence basis required')

    def _statements(self, resolve):
        self._check()
        from .events import _statements_with_proofs
        return _statements_with_proofs(self._PrefixProofIndex__events, self, resolve)

    def _source_index(self, statements):
        self._check()
        from .lifecycle import SourceIndex
        index = SourceIndex.__new__(SourceIndex)
        index._initialize(self._PrefixProofIndex__events, statements, self)
        return index

    def _records(self, as_of):
        self._check()
        from .payroll import _records_with_proofs
        return _records_with_proofs(self._PrefixProofIndex__events, self, as_of)

    def _configure_runner(self, runner, resolve):
        self._check()
        from .payroll import _OwnedFundingRunner
        if type(runner) is not _OwnedFundingRunner:
            raise TypeError('private funding runner required')
        _OwnedFundingRunner._initialize(runner, self._PrefixProofIndex__events, self, resolve, self.__by_id)

    def _destinations(self, as_of, sources):
        self._check()
        from .payroll import _destinations_with_index
        return _destinations_with_index(self._PrefixProofIndex__events, as_of,
                                       self._source_index(sources))

    def _plan_healing(self, runner, root, *, copy=False):
        self._check()
        from .payroll import _OwnedFundingRunner
        if (type(runner) is not _OwnedFundingRunner
                or not _OwnedFundingRunner._uses_owned(runner, self)):
            raise TypeError('private healing runner required')
        return _OwnedFundingRunner._plan_owned(runner, self._PrefixProofIndex__events,
                                              self, root, copy=copy)


def _require_owned(value):
    if type(value) is not _OwnedEvidence:
        raise TypeError('genuine private evidence basis required')
    _OwnedEvidence._check(value)
    return value
