"""Where configuration comes from, and what it is allowed to decide."""

from __future__ import annotations

from viva.env import env_file, load_dotenv


# ----------------------------------------------------------------- the .env

def test_a_dotenv_in_the_working_directory_is_not_configuration(tmp_path, monkeypatch):
    """It used to be. `load_dotenv` defaulted to the relative path `.env`, so a
    file left in a cloned repo, an unpacked starter kit or a shared vault
    directory could set the model base URL and HTTPS_PROXY — and every page
    image of every statement would be posted to a host of its author's choosing
    with the real API key in the header, silently."""
    monkeypatch.delenv("VIVA_ENV_FILE", raising=False)
    monkeypatch.delenv("ORIONVIVA_HOSTILE_MARKER", raising=False)
    (tmp_path / ".env").write_text(
        "ORIONVIVA_HOSTILE_MARKER=attacker.example.com\n"
        "HTTPS_PROXY=http://attacker.example.com:8080\n")
    monkeypatch.chdir(tmp_path)

    load_dotenv()
    import os
    assert os.environ.get("ORIONVIVA_HOSTILE_MARKER") is None
    assert env_file() != tmp_path / ".env"


def test_the_same_file_is_chosen_whatever_the_working_directory(tmp_path, monkeypatch):
    """The search order is derived from this module's own location and the
    user's home, never from where the process was started, so no caller's
    directory can introduce a candidate."""
    monkeypatch.delenv("VIVA_ENV_FILE", raising=False)
    here = env_file()
    monkeypatch.chdir(tmp_path)
    assert env_file() == here


def test_an_explicit_file_is_still_honoured(tmp_path, monkeypatch):
    """The bench harness names one directly, and a person may point at one."""
    named = tmp_path / "chosen.env"
    named.write_text("ORIONVIVA_TEST_EXPLICIT=yes\n")
    monkeypatch.setenv("VIVA_ENV_FILE", str(named))
    assert env_file() == named
