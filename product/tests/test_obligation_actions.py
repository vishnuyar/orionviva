"""Quiet findings cross the bridge as stake-scoped, reversible decisions."""

from viva.desktop_bridge.handlers import (OBLIGATIONS_OPERATIONS,
                                          BridgeRequestError,
                                          handlers_for_opened_vault)
from viva.desktop_bridge.obligation_actions import ObligationActions
from viva.ledger import account_opened, simple_transaction
from viva.ledger.events import CORROBORATED, merchant_enriched
from viva.vault import Vault


def _vault(tmp_path):
    vault = Vault.open(tmp_path / "vault", "pw")
    vault.ledger.append(account_opened(
        "checking", "depository", "Checking", "USD", "2026-01-01"))
    for month in range(1, 5):
        vault.ledger.append(simple_transaction(
            "checking", "-14.99", "LUMEN STREAMING",
            f"2026-{month:02d}-05", kind="depository"))
    vault.ledger.append(merchant_enriched(
        "lumen streaming", "services", occurred_at="2026-01-01",
        grade=CORROBORATED,
        attributes={"counterparty_kind": "business", "billing": "standing",
                    "billing_period": "monthly"}))
    return vault


def test_set_aside_appends_the_exact_live_stake_and_quiets_the_finding(tmp_path):
    vault = _vault(tmp_path)
    today = "2026-04-10"
    finding = vault.ledger.projection().findings(today)[0]

    outcome = ObligationActions(vault, today=lambda: today).set_aside(
        {"finding_id": finding.id})

    assert outcome["kind"] == "set_aside" and outcome["message"]
    projection = vault.ledger.projection()
    assert finding.id not in {row.id for row in projection.findings(today)}
    assert projection.finding_set_asides()[finding.id]["stake"] == finding.stake


def test_stale_or_malformed_finding_actions_write_nothing(tmp_path):
    vault = _vault(tmp_path)
    actions = ObligationActions(vault, today=lambda: "2026-04-10")
    before = len(list(vault.events()))

    assert actions.set_aside({"finding_id": "not-live"})["kind"] == "stale"
    assert len(list(vault.events())) == before
    for payload in ({}, {"finding_id": ""},
                    {"finding_id": "x", "extra": True}):
        try:
            actions.set_aside(payload)
        except BridgeRequestError:
            pass
        else:
            raise AssertionError("malformed finding action was accepted")
    assert len(list(vault.events())) == before


def test_opened_vault_allowlist_serves_the_registered_finding_action(tmp_path):
    dispatcher = handlers_for_opened_vault(_vault(tmp_path))

    assert OBLIGATIONS_OPERATIONS["set_aside_finding"] in dispatcher.handlers
