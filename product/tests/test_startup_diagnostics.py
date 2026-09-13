from __future__ import annotations

import json

import pytest

from viva.startup_diagnostics import emit, span


def test_startup_diagnostic_record_has_only_the_privacy_allowlist(monkeypatch, capsys):
    monkeypatch.setenv("VIVA_STARTUP_DIAGNOSTICS", "1")
    with span("surface", surface="overview"):
        pass
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert len(records) == 2
    assert all(set(record) == {"kind", "operation", "surface", "duration_ms", "state"}
               for record in records)
    assert [record["state"] for record in records] == ["started", "completed"]
    assert all(isinstance(record["duration_ms"], int) for record in records)


def test_startup_diagnostics_reject_free_form_identifiers(monkeypatch):
    monkeypatch.setenv("VIVA_STARTUP_DIAGNOSTICS", "1")
    with pytest.raises(ValueError):
        emit("surface", "completed", surface="/private/vault")
    with pytest.raises(ValueError):
        emit("event count: 400", "completed")


def test_priority_overview_accounts_has_allowlisted_diagnostic_span(monkeypatch, capsys):
    monkeypatch.setenv("VIVA_STARTUP_DIAGNOSTICS", "1")
    with span("surface", surface="overview_accounts"):
        pass
    records = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert [record["state"] for record in records] == ["started", "completed"]
    assert all(record["surface"] == "overview_accounts" for record in records)
    assert all(set(record) == {"kind", "operation", "surface", "duration_ms", "state"}
               for record in records)
