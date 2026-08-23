"""Configuration: a proposal, and the yes that applies it.

Two settings, and they are not the same kind of thing. How figures are written
sends nothing. Naming a model is the moment bytes become able to leave. Every
test here is about keeping those two apart, and about a yes naming exactly what
it is a yes to.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from viva import configuration
from viva.configuration import (ConfigurationError, apply, current,
                                propose_model, propose_presentation)
from viva.desktop_bridge.handlers import default_handlers
from viva.desktop_bridge.rpc import dispatch_frame
from viva.persona import moment
from viva.surface import CURRENT_PROTOCOL

PROPOSE = "viva.settings.propose"
CONFIRM = "viva.settings.confirm"
READ = "viva.settings.read"


@pytest.fixture(autouse=True)
def elsewhere(tmp_path: Path, monkeypatch):
    """Every test writes into its own home, and starts from a clean environment.

    Configuration reads the environment first, so a test that inherited the
    developer's own model settings would be testing their machine."""
    monkeypatch.setattr(configuration, "SETTINGS_FILE", tmp_path / "settings.json")
    monkeypatch.setattr(configuration, "SECRETS_FILE", tmp_path / ".env")
    monkeypatch.setattr(configuration, "CONFIG_HOME", tmp_path)
    monkeypatch.setattr(configuration, "_EXPLICIT_ENVIRONMENT", set())
    for name in (configuration.LOCALE_VAR, configuration.CURRENCY_VAR,
                 configuration.ADAPTER_VAR, configuration.MODEL_VAR,
                 configuration.BASE_URL_VAR, configuration.KEY_ENV_VAR,
                 configuration.KEY_NAME):
        monkeypatch.delenv(name, raising=False)
    yield


def _frame(operation: str, payload: dict) -> str:
    return json.dumps({"protocol": CURRENT_PROTOCOL.wire(), "request_id": "r1",
                       "operation": operation, "payload": payload})


def _send(operation: str, payload: dict) -> dict:
    return json.loads(dispatch_frame(_frame(operation, payload),
                                     default_handlers().handlers))


# --------------------------------------------------------------- the carve-out


def test_the_presentation_path_has_nowhere_to_put_a_model():
    """The carve-out is a signature with no room in it rather than a check a
    later edit could relax."""
    with pytest.raises(TypeError):
        propose_presentation(adapter="anthropic")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        propose_presentation(key="secret")  # type: ignore[call-arg]


def test_changing_how_figures_are_written_declares_that_it_sends_nothing():
    proposal = propose_presentation(locale="en-IN", currency="inr")

    assert proposal.sends is False
    assert proposal.changes == {"locale": "en-IN", "currency": "INR"}


def test_naming_a_model_always_declares_that_it_sends():
    proposal = propose_model(adapter="anthropic", model="a-pinned-1", key="k")

    assert proposal.sends is True


def test_taking_the_permission_back_travels_on_the_same_path():
    """Naming nothing is a change to the same permission, so it declares that
    it sends rather than reading as a harmless tidy-up."""
    proposal = propose_model()

    assert proposal.sends is True
    assert proposal.changes == {"adapter": "", "model": "", "base_url": ""}


# ------------------------------------------------------------------ refusing


def test_a_way_of_writing_numbers_nobody_knows_changes_nothing():
    with pytest.raises(ConfigurationError) as raised:
        propose_presentation(locale="qq-ZZ")

    assert raised.value.reason == "locale_unknown"


def test_a_currency_that_is_not_three_letters_changes_nothing():
    with pytest.raises(ConfigurationError) as raised:
        propose_presentation(currency="dollars")

    assert raised.value.reason == "currency_unknown"


def test_a_model_named_by_an_alias_is_refused():
    """An alias silently becomes a different model later, and a vault's
    recorded reads would then name something nobody chose."""
    for name in ("claude-latest", "gpt-current", "something-newest"):
        with pytest.raises(ConfigurationError) as raised:
            propose_model(adapter="anthropic", model=name, key="k")
        assert raised.value.reason == "model_unnamed"


def test_a_model_with_no_key_anywhere_is_refused():
    with pytest.raises(ConfigurationError) as raised:
        propose_model(adapter="anthropic", model="a-pinned-1")

    assert raised.value.reason == "key_missing"


def test_a_model_may_need_no_key_only_when_the_person_says_so():
    proposal = propose_model(adapter="openai-compatible", model="a-pinned-1",
                             base_url="https://example.invalid/v1",
                             key_action="none")

    assert proposal.changes == {
        "adapter": "openai-compatible", "model": "a-pinned-1",
        "base_url": "https://example.invalid/v1", "key": "not needed",
    }

    settings = apply(proposal, proposal.digest)

    assert settings.can_send is True
    assert os.environ[configuration.KEY_ENV_VAR] == "none"


def test_keyless_takes_effect_after_startup_used_the_default_key_route(
        monkeypatch):
    configuration.SETTINGS_FILE.write_text(json.dumps({
        "adapter": "openai-compatible", "model": "a-pinned-1",
    }), encoding="utf-8")
    configuration.SECRETS_FILE.write_text("", encoding="utf-8")
    monkeypatch.setenv("VIVA_ENV_FILE", str(configuration.SECRETS_FILE))
    configuration.put_stored_in_force()
    assert os.environ[configuration.KEY_ENV_VAR] == configuration.KEY_NAME

    proposal = propose_model(adapter="openai-compatible", model="a-pinned-1",
                             key_action="none")
    apply(proposal, proposal.digest)

    assert os.environ[configuration.KEY_ENV_VAR] == "none"


def test_an_exported_default_key_stays_in_force_when_a_new_key_is_stored(
        monkeypatch):
    monkeypatch.setenv(configuration.KEY_NAME, "exported-synthetic")
    monkeypatch.setenv("VIVA_ENV_FILE", str(configuration.SECRETS_FILE))
    configuration.put_stored_in_force()

    proposal = propose_model(adapter="anthropic", model="a-pinned-1",
                             key="new-synthetic")
    apply(proposal, proposal.digest, key="new-synthetic")

    assert os.environ[configuration.KEY_NAME] == "exported-synthetic"
    assert f"{configuration.KEY_NAME}=new-synthetic" in configuration.SECRETS_FILE.read_text()


def test_a_key_loaded_from_the_credential_store_is_replaced_now(monkeypatch):
    configuration.SECRETS_FILE.write_text(
        f"{configuration.KEY_NAME}=old-stored\n", encoding="utf-8")
    monkeypatch.setenv("VIVA_ENV_FILE", str(configuration.SECRETS_FILE))
    configuration.put_stored_in_force()
    assert os.environ[configuration.KEY_NAME] == "old-stored"

    proposal = propose_model(adapter="anthropic", model="a-pinned-1",
                             key="new-stored")
    apply(proposal, proposal.digest, key="new-stored")

    assert os.environ[configuration.KEY_NAME] == "new-stored"
    assert f"{configuration.KEY_NAME}=new-stored" in configuration.SECRETS_FILE.read_text()


def test_routing_in_the_credential_file_stays_an_explicit_override(monkeypatch):
    configuration.SETTINGS_FILE.write_text(json.dumps({
        "adapter": "anthropic", "model": "debug-model",
    }), encoding="utf-8")
    configuration.SECRETS_FILE.write_text(
        f"{configuration.MODEL_VAR}=debug-model\n"
        f"{configuration.KEY_NAME}=stored-key\n", encoding="utf-8")
    monkeypatch.setenv("VIVA_ENV_FILE", str(configuration.SECRETS_FILE))
    configuration.put_stored_in_force()

    proposal = propose_model(adapter="anthropic", model="new-stored-model")
    apply(proposal, proposal.digest)

    assert os.environ[configuration.MODEL_VAR] == "debug-model"
    assert json.loads(configuration.SETTINGS_FILE.read_text())["model"] == "new-stored-model"


def test_the_document_reader_honours_a_key_that_is_not_needed(monkeypatch):
    from viva.ingest import reader as reader_module

    monkeypatch.setenv(configuration.ADAPTER_VAR, "openai-compatible")
    monkeypatch.setenv(configuration.MODEL_VAR, "a-pinned-1")
    monkeypatch.setenv(configuration.KEY_ENV_VAR, "none")
    seen = {}
    monkeypatch.setattr(reader_module, "read_statement",
                        lambda _data, _doc_id, spec, _locale, _currency:
                        seen.setdefault("spec", spec))

    reader, live = reader_module.build_reader()
    reader(b"", "synthetic-document")

    assert live is True
    assert seen["spec"].api_key_env is None


def test_a_way_of_reaching_a_model_nobody_knows_is_refused():
    with pytest.raises(ConfigurationError) as raised:
        propose_model(adapter="carrier-pigeon", model="a-pinned-1", key="k")

    assert raised.value.reason == "adapter_unknown"


def test_the_example_adapter_is_one_the_product_accepts():
    """The copy-and-uncomment path in `.env.example` must configure a usable
    adapter rather than fail only after somebody supplies a real key."""
    example = Path(__file__).resolve().parents[2] / ".env.example"
    line = next(line for line in example.read_text(encoding="utf-8").splitlines()
                if line.startswith("#VIVA_MODEL_ADAPTER="))
    adapter = line.partition("=")[2]

    assert adapter in configuration.ADAPTERS


# -------------------------------------------------------------------- the yes


def test_a_yes_that_names_a_different_proposal_applies_nothing():
    """A person who was shown one thing and confirmed while another was in
    flight has not agreed to what would happen."""
    proposal = propose_presentation(locale="en-IN")

    with pytest.raises(ConfigurationError) as raised:
        apply(proposal, "0000000000000000")

    assert raised.value.reason == "proposal_moved"
    assert current().locale == "en-US"


def test_a_yes_to_the_proposal_that_was_shown_applies_it_and_takes_effect_now():
    """A setting a person applied that takes effect on the next launch is a
    setting that did not take effect."""
    proposal = propose_presentation(locale="en-IN", currency="INR")

    settings = apply(proposal, proposal.digest)

    assert settings.locale == "en-IN"
    assert settings.currency == "INR"
    assert os.environ[configuration.LOCALE_VAR] == "en-IN"


def test_naming_a_model_makes_the_engine_able_to_send_and_says_so():
    proposal = propose_model(adapter="anthropic", model="a-pinned-1", key="a-key")

    settings = apply(proposal, proposal.digest, key="a-key")

    assert settings.can_send is True
    from viva.ingest.reader import live_reading_configured
    assert live_reading_configured() is True


def test_taking_the_permission_back_stops_anything_being_able_to_leave():
    named = propose_model(adapter="anthropic", model="a-pinned-1", key="a-key")
    apply(named, named.digest, key="a-key")

    cleared = propose_model()
    settings = apply(cleared, cleared.digest)

    assert settings.can_send is False
    from viva.ingest.reader import live_reading_configured
    assert live_reading_configured() is False


@pytest.mark.parametrize("key_variable", ["", "none", configuration.KEY_NAME])
@pytest.mark.parametrize("adapter,model", [("", ""), ("anthropic", ""),
                                           ("", "a-pinned-1"),
                                           ("anthropic", "a-pinned-1")])
def test_what_a_person_is_told_and_what_the_reader_gates_on_agree(
        monkeypatch, adapter, model, key_variable):
    """The settings read and ingest gate agree for every keyed state."""
    from viva.ingest.reader import live_reading_configured

    monkeypatch.setenv(configuration.ADAPTER_VAR, adapter)
    monkeypatch.setenv(configuration.MODEL_VAR, model)
    if key_variable:
        monkeypatch.setenv(configuration.KEY_ENV_VAR, key_variable)
        monkeypatch.setenv(key_variable, "a-key")

    assert current().can_send is live_reading_configured()


# -------------------------------------------------------------------- the key


def test_the_key_is_never_in_a_proposal_a_digest_or_a_reply():
    proposal = propose_model(adapter="anthropic", model="a-pinned-1",
                             key="the-actual-secret")

    assert "the-actual-secret" not in json.dumps(proposal.as_dict())
    assert proposal.changes["key"] == "set"
    settings = apply(proposal, proposal.digest, key="the-actual-secret")
    assert "the-actual-secret" not in json.dumps(settings.as_dict())
    assert settings.key_set is True


def test_the_key_is_written_where_only_its_owner_can_read_it():
    """A key that is world-readable for even the moment between writing and
    chmod is a key that leaked, so the file is created narrow."""
    proposal = propose_model(adapter="anthropic", model="a-pinned-1", key="a-key")
    apply(proposal, proposal.digest, key="a-key")

    mode = stat.S_IMODE(configuration.SECRETS_FILE.stat().st_mode)
    assert mode == stat.S_IRUSR | stat.S_IWUSR
    assert "a-key" in configuration.SECRETS_FILE.read_text()


def test_the_settings_file_never_holds_the_key():
    proposal = propose_model(adapter="anthropic", model="a-pinned-1", key="a-key")
    apply(proposal, proposal.digest, key="a-key")

    assert "a-key" not in configuration.SETTINGS_FILE.read_text()


def test_the_settings_file_holds_where_the_key_was_put():
    """Settings persist the key's environment name, never its value."""
    proposal = propose_model(adapter="anthropic", model="a-pinned-1", key="a-key")
    apply(proposal, proposal.digest, key="a-key")

    written = json.loads(configuration.SETTINGS_FILE.read_text())

    assert written[configuration.KEY_ENV_FIELD] == configuration.KEY_NAME


def test_a_change_that_files_no_key_writes_nothing_down_about_where_one_is(
        monkeypatch):
    """A model-only change does not persist an exported key name."""
    monkeypatch.setenv(configuration.KEY_ENV_VAR, "A_NAME_OF_THEIR_OWN")
    monkeypatch.setenv("A_NAME_OF_THEIR_OWN", "a-key")

    proposal = propose_model(adapter="anthropic", model="a-pinned-1")
    apply(proposal, proposal.digest)

    written = json.loads(configuration.SETTINGS_FILE.read_text())

    assert configuration.KEY_ENV_FIELD not in written
    assert os.environ[configuration.KEY_ENV_VAR] == "A_NAME_OF_THEIR_OWN"


def test_a_change_to_how_figures_are_written_records_nothing_about_a_key(
        monkeypatch):
    """A presentation change does not persist credential routing."""
    monkeypatch.setenv(configuration.KEY_ENV_VAR, "A_NAME_OF_THEIR_OWN")
    monkeypatch.setenv("A_NAME_OF_THEIR_OWN", "a-key")

    proposal = propose_presentation(locale="en-IN")
    apply(proposal, proposal.digest)

    written = json.loads(configuration.SETTINGS_FILE.read_text())

    assert configuration.KEY_ENV_FIELD not in written
    assert written["locale"] == "en-IN"
    assert os.environ[configuration.KEY_ENV_VAR] == "A_NAME_OF_THEIR_OWN"


def test_a_presentation_change_does_not_override_an_exported_model(monkeypatch):
    configuration.SETTINGS_FILE.write_text(json.dumps({
        "locale": "en-US", "currency": "USD", "adapter": "anthropic",
        "model": "stored-model-1",
    }), encoding="utf-8")
    monkeypatch.setenv(configuration.MODEL_VAR, "exported-model-1")

    proposal = propose_presentation(locale="en-IN")
    settings = apply(proposal, proposal.digest)

    assert os.environ[configuration.MODEL_VAR] == "exported-model-1"
    assert settings.model == "exported-model-1"


def test_a_refused_settings_write_does_not_write_or_activate_a_key(monkeypatch):
    proposal = propose_model(adapter="anthropic", model="a-pinned-1", key="a-key")

    def refuse(_stored):
        raise ConfigurationError(configuration.UNWRITABLE)

    monkeypatch.setattr(configuration, "_write", refuse)

    with pytest.raises(ConfigurationError) as raised:
        apply(proposal, proposal.digest, key="a-key")

    assert raised.value.reason == configuration.UNWRITABLE
    assert configuration.SECRETS_FILE.exists() is False
    assert configuration.SETTINGS_FILE.exists() is False
    assert os.environ.get(configuration.KEY_NAME) is None


def test_the_one_door_to_the_key_says_a_key_is_there_and_never_which(monkeypatch):
    """The credential accessor reports presence without returning the key."""
    monkeypatch.delenv(configuration.KEY_NAME, raising=False)

    before = configuration.key_store()
    after = configuration.key_store("a-key")

    assert before.held is False
    assert after.held is True
    assert after.variable == configuration.KEY_NAME
    assert "a-key" not in json.dumps(after.__dict__)


# ------------------------------------------------------------- what was stored


def test_a_machine_nobody_configured_reads_as_one_nobody_configured():
    assert configuration.SETTINGS_FILE.exists() is False

    settings = current()

    assert settings.adapter == ""
    assert settings.settings_readable is True


def test_settings_that_cannot_be_read_are_not_reported_as_never_written():
    """An unreadable settings file is reported and left unchanged."""
    configuration.SETTINGS_FILE.write_text("{ not settings at all", encoding="utf-8")

    settings = current()

    assert settings.settings_readable is False
    assert settings.adapter == ""
    assert configuration.SETTINGS_FILE.read_text() == "{ not settings at all"


def test_settings_holding_something_that_is_not_settings_read_as_unreadable():
    configuration.SETTINGS_FILE.write_text('["a list of things"]', encoding="utf-8")

    assert current().settings_readable is False


# ---------------------------------------------------------------- the bridge


def test_settings_are_reachable_before_any_vault_is_open():
    """A build that made a person open a vault first would have made
    configuration a thing you need a vault to reach, and a vault a thing you
    need configuration to use."""
    handlers = default_handlers().handlers

    assert {PROPOSE, CONFIRM, READ} <= set(handlers)


def test_proposing_over_the_bridge_changes_nothing_and_says_what_would():
    answered = _send(PROPOSE, {"kind": "model", "adapter": "anthropic",
                               "model": "a-pinned-1"})

    assert answered["ok"] is True
    # No key anywhere yet, so the proposal itself is refused rather than built.
    assert answered["result"]["kind"] == "refused"
    assert answered["result"]["reason"] == "key_missing"
    assert answered["result"]["message"] == moment("settings_key_missing")


def test_the_bridge_carries_a_new_keys_presence_without_carrying_the_key():
    proposed = _send(PROPOSE, {"kind": "model", "adapter": "anthropic",
                               "model": "a-pinned-1", "key_action": "set"})["result"]

    assert proposed["kind"] == "proposal"
    assert proposed["state"]["changes"]["key"] == "set"
    assert "a-key" not in json.dumps(proposed)

    confirmed = _send(CONFIRM, {"kind": "model", "adapter": "anthropic",
                                "model": "a-pinned-1", "key_action": "set",
                                "digest": proposed["state"]["digest"],
                                "key": "a-key"})["result"]

    assert confirmed["kind"] == "completed"
    assert confirmed["state"]["key_set"] is True
    assert "a-key" not in json.dumps(confirmed)


def test_a_keyless_model_crosses_the_bridge_as_an_explicit_statement():
    proposed = _send(PROPOSE, {"kind": "model",
                               "adapter": "openai-compatible",
                               "model": "a-pinned-1",
                               "base_url": "https://example.invalid/v1",
                               "key_action": "none"})["result"]

    assert proposed["kind"] == "proposal"
    assert proposed["state"]["changes"]["key"] == "not needed"

    confirmed = _send(CONFIRM, {"kind": "model",
                                "adapter": "openai-compatible",
                                "model": "a-pinned-1",
                                "base_url": "https://example.invalid/v1",
                                "key_action": "none",
                                "digest": proposed["state"]["digest"]})["result"]

    assert confirmed["kind"] == "completed"
    assert os.environ[configuration.KEY_ENV_VAR] == "none"
    assert confirmed["message"] == moment("settings_model_keyless_confirmed")


def test_a_presentation_proposal_and_its_yes_cross_the_bridge():
    proposed = _send(PROPOSE, {"kind": "presentation", "locale": "en-IN"})["result"]

    assert proposed["kind"] == "proposal"
    assert proposed["message"] == moment("settings_presentation_proposed")
    assert proposed["state"]["sends"] is False

    confirmed = _send(CONFIRM, {"kind": "presentation", "locale": "en-IN",
                                "digest": proposed["state"]["digest"]})["result"]

    assert confirmed["kind"] == "completed"
    assert confirmed["message"] == moment("settings_presentation_confirmed")
    assert confirmed["state"]["locale"] == "en-IN"


def test_a_key_may_not_be_sent_under_the_kind_that_sends_nothing():
    """The one place the two paths could be joined by a caller, closed as the
    request it is rather than by ignoring the field."""
    answered = _send(CONFIRM, {"kind": "presentation", "locale": "en-IN",
                               "digest": "x", "key": "a-key"})

    assert answered["ok"] is False
    assert answered["error"]["code"] == "invalid_request"


def test_the_read_never_carries_the_key():
    proposal = propose_model(adapter="anthropic", model="a-pinned-1", key="a-key")
    apply(proposal, proposal.digest, key="a-key")

    answered = _send(READ, {})

    assert answered["result"]["can_send"] is True
    assert answered["result"]["key_set"] is True
    assert "a-key" not in json.dumps(answered)


def test_a_request_naming_no_kind_is_refused():
    assert _send(PROPOSE, {"locale": "en-IN"})["error"]["code"] == "invalid_request"
    assert _send(PROPOSE, {"kind": "everything"})["error"]["code"] == "invalid_request"
