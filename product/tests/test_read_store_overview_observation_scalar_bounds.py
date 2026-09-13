"""Current and historical Overview refuse oversized measured scalar inputs."""

import pytest

from viva.demo import build_demo_vault
from viva.desktop_bridge.handlers import BridgeRequestError
from viva.desktop_bridge.vault_surface import OpenedVaultSurfaceProvider
from viva.read_store.scalar_bounds import MAX_SCALAR_BYTES
from viva.read_store.store import ReadStoreError
from viva.surface.overview import overview


@pytest.mark.parametrize("glyph", ["X", "雪"])
@pytest.mark.parametrize("table,column", [
    ("balance_observations", "provenance_note"),
    ("positions", "instrument_id"),
    ("positions", "provenance_note"),
])
def test_overview_measurement_scalar_exact_utf8_boundary_and_refusal(
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
            f"UPDATE {table} SET {column}=? WHERE rowid=(SELECT rowid FROM "
            f"{table} LIMIT 1)", (value,)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            assert revision.connection.execute(
                f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0] == value
            for historical in (False, True):
                traced = []
                revision.connection.set_trace_callback(traced.append)
                read = (lambda: revision.historical_overview_projection(
                    as_of="9999-12-31", today="2026-08-29") if historical
                    else revision.overview_projection(today="2026-08-29"))
                if extra:
                    with pytest.raises(ReadStoreError, match="scalar byte bound"):
                        read()
                else:
                    read()
                revision.connection.set_trace_callback(None)
                selected = [sql for sql in traced
                            if (f"CAST({column} AS BLOB)" in sql or
                                f"CAST(b.{column} AS BLOB)" in sql)
                            and f"FROM {table}" in sql]
                assert selected
                plan = " ".join(str(row[-1]) for row in
                                revision.connection.execute(
                                    "EXPLAIN QUERY PLAN " + selected[-1]).fetchall())
                assert "TEMP B-TREE" not in plan.upper()
        if extra:
            provider = OpenedVaultSurfaceProvider(vault)
            for parameters in ({"read_on": "2026-08-29"},
                               {"as_of": "9999-12-31", "read_on": "2026-08-29"}):
                with pytest.raises(BridgeRequestError):
                    provider.read_surface("overview", parameters)


def test_overview_measurement_held_complete_payload_survives_bad_successor(tmp_path):
    vault = build_demo_vault(tmp_path / "sample")
    held = vault.read_store.open_reader()
    before = overview(held.overview_projection(today="2026-08-29"),
                      "en-US", "2026-08-29")
    vault.read_store.publish(lambda db: db.execute(
        "UPDATE positions SET provenance_note=?",
        ("X" * (MAX_SCALAR_BYTES + 1),)), copy_current=True)
    assert overview(held.overview_projection(today="2026-08-29"),
                    "en-US", "2026-08-29") == before
    with vault.read_store.open_reader() as current:
        with pytest.raises(ReadStoreError, match="scalar byte bound"):
            current.overview_projection(today="2026-08-29")
    held.close()


@pytest.mark.parametrize("table,column", [
    ("balance_observations", "amount_text"),
    ("positions", "value_text"),
])
def test_overview_decimal_lexical_value_has_exact_scalar_limit(tmp_path, table, column):
    vault = build_demo_vault(tmp_path / "sample")
    with vault.read_store.open_reader() as revision:
        original = revision.connection.execute(
            f"SELECT {column} FROM {table} LIMIT 1").fetchone()[0]
    padding = "0" * (MAX_SCALAR_BYTES - len(original.encode("utf-8")))
    for extra in ("", "0"):
        value = original + padding + extra
        assert len(value.encode("utf-8")) == MAX_SCALAR_BYTES + len(extra)
        vault.read_store.publish(lambda db: db.execute(
            f"UPDATE {table} SET {column}=? WHERE rowid=(SELECT rowid FROM "
            f"{table} LIMIT 1)", (value,)), copy_current=True)
        with vault.read_store.open_reader() as revision:
            if extra:
                with pytest.raises(ReadStoreError, match="scalar byte bound"):
                    revision.overview_projection(today="2026-08-29")
            else:
                revision.overview_projection(today="2026-08-29")
