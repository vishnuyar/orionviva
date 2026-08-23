"""Configuration replay across a fresh sidecar process."""

from __future__ import annotations

import json
import pathlib
import subprocess
import sys

from viva.configuration import KEY_NAME
from viva.surface import CURRENT_PROTOCOL

ROOT = pathlib.Path(__file__).resolve().parents[2]

# Start the sidecar, then record its non-secret environment and key presence.
RUNNER = """
import json, os, sys
from viva.desktop_bridge.__main__ import main

main()

named = ("VIVA_LOCALE", "VIVA_CURRENCY", "VIVA_MODEL_ADAPTER", "VIVA_MODEL",
         "VIVA_MODEL_BASE_URL", "VIVA_MODEL_KEY_ENV")
running_under = {name: os.environ.get(name, "") for name in named}
running_under["key_is_there"] = bool(
    os.environ.get(os.environ.get("VIVA_MODEL_KEY_ENV", "")))
pathlib = __import__("pathlib")
pathlib.Path(sys.argv[1]).write_text(json.dumps(running_under), encoding="utf-8")
"""

# A stored configuration using a synthetic, non-default key name.
KEY_VARIABLE = "A_MADE_UP_KEY_VARIABLE"
INVENTED_KEY = "not-a-key-just-letters"
STORED = {
    "locale": "en-IN",
    "currency": "INR",
    "adapter": "openai-compatible",
    "model": "a-pinned-1",
    "base_url": "https://example.invalid/v1",
    "key_env": KEY_VARIABLE,
}


def _machine(where: pathlib.Path, settings: str | None,
             env_lines: str = "") -> pathlib.Path:
    """A home directory holding what an earlier run of the app left behind."""
    config = where / ".orionviva"
    config.mkdir(parents=True)
    if settings is not None:
        (config / "settings.json").write_text(settings, encoding="utf-8")
    (config / ".env").write_text(env_lines, encoding="utf-8")
    return where


def _started(home: pathlib.Path, exported: dict[str, str] | None = None,
             ) -> tuple[dict, dict]:
    """Return the sidecar's settings reply and effective environment."""
    observed = home / "running-under.json"
    frame = json.dumps({"protocol": CURRENT_PROTOCOL.wire(), "request_id": "r1",
                        "operation": "viva.settings.read", "payload": {}})
    environment = {
        "PYTHONPATH": f"{ROOT}:{ROOT / 'product'}:{ROOT / 'core'}:{ROOT / 'merchant'}",
        "PATH": "/usr/bin:/bin",
        "HOME": str(home),
        # Pin the test file so the developer's configuration is never searched.
        "VIVA_ENV_FILE": str(home / ".orionviva" / ".env"),
    }
    environment.update(exported or {})
    done = subprocess.run(
        [sys.executable, "-c", RUNNER, str(observed)],
        cwd=ROOT, input=frame + "\n", capture_output=True, text=True,
        env=environment)
    assert done.returncode == 0, done.stderr
    answered = json.loads(done.stdout.splitlines()[0])
    assert answered["ok"] is True, answered
    assert INVENTED_KEY not in done.stdout
    return answered["result"], json.loads(observed.read_text(encoding="utf-8"))


def test_a_configuration_applied_before_is_in_force_in_a_new_process(tmp_path):
    """A fresh sidecar puts every stored routing field in force."""
    home = _machine(tmp_path, json.dumps(STORED), f"{KEY_VARIABLE}={INVENTED_KEY}\n")

    answered, running_under = _started(home)

    assert running_under["VIVA_MODEL_ADAPTER"] == STORED["adapter"]
    assert running_under["VIVA_MODEL"] == STORED["model"]
    assert running_under["VIVA_MODEL_BASE_URL"] == STORED["base_url"]
    assert running_under["VIVA_LOCALE"] == STORED["locale"]
    assert running_under["VIVA_CURRENCY"] == STORED["currency"]
    assert answered["can_send"] is True


def test_the_key_is_looked_for_under_the_name_it_was_filed_under(tmp_path):
    """A fresh sidecar uses the stored key environment name."""
    home = _machine(tmp_path / "one", json.dumps(STORED),
                    f"{KEY_VARIABLE}={INVENTED_KEY}\n")
    elsewhere = _machine(tmp_path / "two", json.dumps(STORED),
                         "A_DIFFERENT_VARIABLE=nothing-of-use\n")

    answered, running_under = _started(home)
    missing, _ = _started(elsewhere)

    assert running_under["VIVA_MODEL_KEY_ENV"] == KEY_VARIABLE
    assert running_under["key_is_there"] is True
    assert answered["key_set"] is True
    assert missing["key_set"] is False


def test_where_a_key_is_read_from_is_in_force_even_when_nothing_named_it(tmp_path):
    """Legacy settings without a key name use the credential-store default."""
    named_no_key = {name: value for name, value in STORED.items() if name != "key_env"}
    home = _machine(tmp_path, json.dumps(named_no_key), f"{KEY_NAME}={INVENTED_KEY}\n")

    answered, running_under = _started(home)

    assert running_under["VIVA_MODEL"] == STORED["model"]
    assert running_under["VIVA_MODEL_KEY_ENV"] == KEY_NAME
    assert running_under["key_is_there"] is True
    assert answered["key_set"] is True
    assert answered["can_send"] is True


def test_something_said_at_the_point_of_running_still_wins(tmp_path):
    """An explicit environment value overrides the stored value."""
    home = _machine(tmp_path, json.dumps(STORED), f"{KEY_VARIABLE}={INVENTED_KEY}\n")

    answered, running_under = _started(home, exported={"VIVA_MODEL": "a-said-so-1"})

    assert running_under["VIVA_MODEL"] == "a-said-so-1"
    assert answered["model"] == "a-said-so-1"
    assert running_under["VIVA_MODEL_ADAPTER"] == STORED["adapter"]


def test_a_machine_that_was_never_configured_names_no_model(tmp_path):
    """An unconfigured machine names no model and uses the default key name."""
    home = _machine(tmp_path, None)

    answered, running_under = _started(home)

    assert running_under["VIVA_MODEL_ADAPTER"] == ""
    assert running_under["VIVA_MODEL"] == ""
    assert running_under["VIVA_MODEL_KEY_ENV"] == KEY_NAME
    assert answered["can_send"] is False


# --------------------------------------- what a started machine says it holds


def test_a_started_machine_says_when_its_settings_cannot_be_read(tmp_path):
    """A fresh sidecar reports unreadable settings without modifying them."""
    unreadable = "{ this is not settings"
    home = _machine(tmp_path, unreadable)

    answered, _ = _started(home)

    assert answered["settings_readable"] is False
    assert answered["can_send"] is False
    assert (home / ".orionviva" / "settings.json").read_text(encoding="utf-8") == unreadable


def test_a_started_machine_with_nothing_stored_says_so_rather_than_saying_broken(
        tmp_path):
    answered, _ = _started(_machine(tmp_path, None))

    assert answered["settings_readable"] is True
    assert answered["adapter"] == ""
