"""Private immutable commitments issued from independent complete verification."""
from dataclasses import dataclass, field, replace
import hashlib
import json
import os

from .store import IntegrityError

_SEAL = object()


def _wire(value):
    return json.dumps(value,sort_keys=True,separators=(",",":"),ensure_ascii=False,allow_nan=False).encode()


def _digest(value):
    return hashlib.sha256(_wire(value)).hexdigest()


def _table_digest(table, columns, rows):
    return _digest([table,list(columns),sorted((_wire(row).decode() for row in rows))])


@dataclass(frozen=True)
class _RepresentationProof:
    history: tuple
    terminal_digest: str
    terminal_wire: bytes
    metadata: tuple
    originals: tuple
    original_members: tuple
    schema_contract: str
    pending: bool
    locks: tuple = ()
    seal: object = field(repr=False,compare=False,default=None)

    def __post_init__(self):
        if (self.seal is not _SEAL or type(self.history) is not tuple or type(self.metadata) is not tuple
                or type(self.originals) is not tuple or type(self.original_members) is not tuple
                or type(self.terminal_wire) is not bytes or type(self.pending) is not bool
                or type(self.locks) is not tuple or any(type(row) is not tuple or len(row)!=7
                    or type(row[0]) is not str or type(row[6]) is not str
                    or any(type(v) is not int for v in row[1:6]) for row in self.locks)
                or any(type(row) is not tuple or len(row)!=2 or any(type(value) is not str for value in row)
                       for row in self.history+self.metadata)
                or any(type(row) is not tuple or len(row)!=3 or type(row[0]) is not str
                       or type(row[1]) is not str or type(row[2]) is not int for row in self.originals)
                or any(type(name) is not str for name in self.original_members)):
            raise IntegrityError("unissued or mutable representation proof")


@dataclass(frozen=True)
class _VerificationProof:
    owner_id: int
    pid: int
    root_id: str
    implementation: str
    representation: _RepresentationProof
    sql_digest: str
    tables: tuple
    seal: object = field(repr=False,compare=False,default=None)

    def __post_init__(self):
        if (self.seal is not _SEAL or type(self.representation) is not _RepresentationProof
                or type(self.tables) is not tuple
                or any(type(row) is not tuple or len(row)!=2 or any(type(value) is not str for value in row) for row in self.tables)):
            raise IntegrityError("unissued complete verification proof")


def _representation(history,terminal_wire,metadata,originals,members,schema_contract,pending,locks=()):
    return _RepresentationProof(tuple(history),hashlib.sha256(terminal_wire).hexdigest(),bytes(terminal_wire),
        tuple(metadata),tuple(originals),tuple(members),schema_contract,bool(pending),tuple(locks),_SEAL)


def _verified(owner,representation,sql_digest,tables):
    return _VerificationProof(id(owner),os.getpid(),owner._metadata['root_id'],
        _context_digest(owner),representation,sql_digest,tuple(tables),_SEAL)


def _context_digest(owner):
    from .reading import current_read_context
    return _digest(current_read_context(owner._engine._implementation_identity))


def _owner(proof,owner):
    if (type(proof) is not _VerificationProof or proof.seal is not _SEAL
            or proof.owner_id!=id(owner) or proof.pid!=os.getpid()
            or proof.root_id!=owner._metadata['root_id']
            or proof.implementation!=_context_digest(owner)):
        raise IntegrityError("complete proof ownership or source closure differs")


def _promoted(proof,owner):
    _owner(proof,owner)
    return replace(proof,representation=replace(proof.representation,pending=False))
