"""SQL-side byte limits for bounded read-model scalar inputs."""

from .store import ReadStoreError


MAX_SCALAR_BYTES = 4_096


def selected(columns, numeric=()):
    names = tuple(columns)
    selected_columns = [
        name if name in numeric else
        f"CASE WHEN {name} IS NULL THEN NULL "
        f"WHEN length(CAST({name} AS BLOB))<=? THEN {name} ELSE 1 END"
        for name in names]
    return ",".join(selected_columns), (MAX_SCALAR_BYTES,) * (
        len(names) - len(numeric))


def refuse(rows, columns, numeric=(), *, label):
    names = tuple(columns)
    for row in rows:
        if any(type(value) is int and value == 1
               for name, value in zip(names, row) if name not in numeric):
            raise ReadStoreError(f"{label} exceeds its scalar byte bound")
