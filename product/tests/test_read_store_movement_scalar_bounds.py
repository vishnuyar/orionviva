"""Read-time movement and posting scalars are bounded before Python fetch."""

import pytest

from viva.demo import build_demo_vault
from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.read_store.scalar_bounds import MAX_SCALAR_BYTES
from viva.read_store.store import ReadStoreError
from viva.read_store.temporal_activity import eligible_postings


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("table,column", [
    ("movements", "description"), ("movements", "provenance_note"),
    ("transactions", "description"), ("transactions", "provenance_note"),
])
def test_shared_movement_scalar_exact_utf8_boundary_and_complete_refusal(
        tmp_path, glyph, table, column):
    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0]
    assert isinstance(original, str)
    room = MAX_SCALAR_BYTES - len(original.encode("utf-8"))
    width = len(glyph.encode("utf-8"))
    padding = glyph * (room // width) + "X" * (room % width)
    for extra in ("", "X"):
        value = original + padding + extra
        assert len(value.encode("utf-8")) == MAX_SCALAR_BYTES + len(extra)
        vault.read_store.publish(lambda db: db.execute(
            f"UPDATE {table} SET {column}=? WHERE rowid=(SELECT rowid "
            f"FROM {table} LIMIT 1)", (value,)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            assert revision.connection.execute(
                f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0] == value
            traced = []
            revision.connection.set_trace_callback(traced.append)
            if table == "movements":
                read = lambda: revision.activity_projection().movements()
            else:
                read = lambda: eligible_postings(revision, "9999-12-31")
            if extra:
                with pytest.raises(ReadStoreError, match="scalar byte bound"):
                    read()
            else:
                assert read()
            revision.connection.set_trace_callback(None)
            bounded = [sql for sql in traced
                       if f"CAST({column} AS BLOB)" in sql
                       or f"CAST(t.{column} AS BLOB)" in sql]
            assert bounded
            plan = " ".join(str(row[-1]) for row in revision.connection.execute(
                "EXPLAIN QUERY PLAN " + bounded[-1]).fetchall())
            assert "TEMP B-TREE" not in plan.upper()
        if extra:
            provider = OpenedVaultSurfaceProvider(vault)
            route = "activity"
            params = ({"as_of": "9999-12-31"} if table == "transactions"
                      else {})
            with pytest.raises(BridgeRequestError):
                provider.read_surface(route, params)


@pytest.mark.parametrize("table", ["movements", "transactions"])
def test_empty_provenance_note_remains_distinct_from_oversized_refusal(
        tmp_path, table):
    vault = build_demo_vault(tmp_path / "sample")
    vault.read_store.publish(lambda db: db.execute(
        f"UPDATE {table} SET provenance_note='' WHERE rowid=(SELECT rowid "
        f"FROM {table} LIMIT 1)"), copy_current=True)
    with vault.read_store.open_reader() as revision:
        if table == "movements":
            assert revision.activity_projection().movements()
        else:
            assert eligible_postings(revision, "9999-12-31")
