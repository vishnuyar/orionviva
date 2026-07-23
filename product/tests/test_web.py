"""The web surface: the service layer, and a live localhost round-trip."""

import json
import threading
import urllib.request
from decimal import Decimal

from viva.vault import Vault
from viva.web import serve, service
from viva.web.sample import seed_sample


def _vault(tmp):
    v = Vault.open(tmp / "vault", "pw")
    seed_sample(v)
    return v


def test_overview_payload(tmp_path):
    ov = service.overview(_vault(tmp_path))
    assert ov["total"]["amount"] == "6913.28" and ov["total"]["currency"] == "USD"
    names = {a["name"] for a in ov["accounts"]}
    assert "Northwind Checking 4021" in names and "Cedar Savings 7788" in names
    assert ov["review_count"] == 1              # the held February statement
    assert "posted" in ov["coverage"]


def test_account_view_has_transactions_and_provenance(tmp_path):
    d = service.account_view(_vault(tmp_path), "acct:northwind-checking-4021")
    assert d["balance"]["grade"] == "corroborated"
    assert len(d["transactions"]) == 3
    assert d["transactions"][0]["provenance"]["doc_id"]   # provenance rides along


def test_auto_corrected_account_posted(tmp_path):
    # Cedar's misread Fee line was forced-corrected by its running balance.
    d = service.account_view(_vault(tmp_path), "acct:cedar-savings-7788")
    assert d["balance"]["amount"] == "1487.58"


def test_confirm_resolves_a_held_item(tmp_path):
    v = _vault(tmp_path)
    item = service.review_list(v)["items"][0]
    res = service.confirm_correction(v, item["doc_id"], "amount", "115.00", 0)
    assert res["action"] == "posted" and res["grade"] == "verified"
    assert service.overview(v)["review_count"] == 0


def test_unknown_account_view_is_honest(tmp_path):
    d = service.account_view(_vault(tmp_path), "acct:nope")
    assert d["error"] == "unknown_account"


def test_reader_factory_gates_on_env(monkeypatch):
    from viva.web.__main__ import build_reader
    for k in ("VIVA_MODEL_ADAPTER", "VIVA_MODEL"):
        monkeypatch.delenv(k, raising=False)
    read_fn, live = build_reader()
    assert live is False                       # no model configured -> parks

    monkeypatch.setenv("VIVA_MODEL_ADAPTER", "anthropic")
    monkeypatch.setenv("VIVA_MODEL", "claude-pinned-2026")
    monkeypatch.setenv("VIVA_MODEL_KEY_ENV", "SOME_KEY")
    read_fn, live = build_reader()
    assert live is True and callable(read_fn)   # built, but no call made here


def test_live_server_serves_overview(tmp_path):
    v = _vault(tmp_path)
    httpd = serve(v, lambda data, doc_id: None, "127.0.0.1", 0)
    port = httpd.server_address[1]
    t = threading.Thread(target=httpd.serve_forever, daemon=True)
    t.start()
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/overview") as r:
            payload = json.loads(r.read())
        assert payload["total"]["amount"] == "6913.28"
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r:
            assert b"<title>Viva</title>" in r.read()
    finally:
        httpd.shutdown()
