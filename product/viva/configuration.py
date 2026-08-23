"""What this machine has been told to do, and the yes that told it.

Two settings live here and they are not the same kind of thing at all.

**How figures are written** — the locale a number is set down under and the
currency a total is labelled with — sends nothing anywhere. It changes the
digits on a screen and nothing else.

**Which model may be reached** is the moment bytes become able to leave. Until
a model is named, no document page and no question can go anywhere, whatever
else is configured; once one is, both can. That is an irreversible act in the
only sense that matters — undoing it does not unsend what was sent — so it
waits for an explicit yes to the exact thing a person was shown.

The two are kept apart **structurally**, not by a rule saying they should be.
There are two proposal builders and two apply paths, and the presentation one
cannot carry a model field: not because it checks, but because it has nowhere
to put one. A carve-out written as a promise to behave is not a carve-out.

**A yes names what it is a yes to.** A proposal carries a digest of the exact
changes it describes, and applying one requires that digest. A person who was
shown one thing and confirms while something else is in flight applies nothing.

**Nothing here needs a terminal.** The settings are written to a file the
engine already reads, in the one place it already looks, and a key is written
with permissions that keep it to its owner. A person never has to know what an
environment variable is.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from .env import CONFIG_HOME

log = logging.getLogger(__name__)

# Where the applied configuration is written. Beside the `.env` the engine
# already reads, in the directory it already looks in, so a packaged install
# and a checkout resolve the same place.
SETTINGS_FILE = CONFIG_HOME / "settings.json"
SECRETS_FILE = CONFIG_HOME / ".env"

# The environment variables each setting is in force as. The engine reads these
# names and nothing else, so this table is the whole of the join between what a
# person chose and what the reader does.
LOCALE_VAR = "VIVA_LOCALE"
CURRENCY_VAR = "VIVA_CURRENCY"
ADAPTER_VAR = "VIVA_MODEL_ADAPTER"
MODEL_VAR = "VIVA_MODEL"
BASE_URL_VAR = "VIVA_MODEL_BASE_URL"
KEY_ENV_VAR = "VIVA_MODEL_KEY_ENV"

# The name the key itself is written under. One name, chosen here rather than
# by a person, because a person choosing the name of an environment variable is
# exactly the thing X1 says no feature may require.
KEY_NAME = "VIVA_MODEL_API_KEY"

# The settings-file field holding the environment name used for the key.
KEY_ENV_FIELD = "key_env"

# The environment name for every non-secret stored setting.
_IN_FORCE = (("locale", LOCALE_VAR), ("currency", CURRENCY_VAR),
             ("adapter", ADAPTER_VAR), ("model", MODEL_VAR),
             ("base_url", BASE_URL_VAR))


def _present_environment() -> set[str]:
    """Environment names supplied before stored settings are replayed."""
    names = {variable for _, variable in _IN_FORCE}
    names.update((KEY_ENV_VAR, KEY_NAME))
    selected = os.environ.get(KEY_ENV_VAR, "").strip()
    if selected:
        names.add(selected)
    return {name for name in names if name in os.environ}


_EXPLICIT_ENVIRONMENT = _present_environment()

# The ways of reaching a model this build knows. Read from the one place that
# resolves them, so a name this list admits is a name the adapter registry can
# actually build.
ADAPTERS = ("anthropic", "openai-compatible")

# Names that are not a model. A pinned id is required because an alias silently
# becomes a different model later, and a vault's recorded reads would then name
# something nobody chose.
_UNPINNED = ("latest", "current", "newest")


class ConfigurationError(ValueError):
    """A setting could not be applied, and nothing was changed."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# Why a proposal was refused, in the machine's own words. Each is paired with
# exactly one reviewed sentence where the reply is built.
UNKNOWN_LOCALE = "locale_unknown"
UNKNOWN_CURRENCY = "currency_unknown"
UNKNOWN_ADAPTER = "adapter_unknown"
UNPINNED_MODEL = "model_unnamed"
MISSING_KEY = "key_missing"
UNWRITABLE = "settings_unwritable"
NOT_THE_PROPOSAL = "proposal_moved"


@dataclass(frozen=True)
class Configuration:
    """What is in force, as a screen may read it.

    The key itself is never here, and there is no accessor that would return
    it. A screen may know whether one is in use; naming an adapter and model is
    the separate permission that decides whether outbound work is possible."""

    locale: str
    currency: str
    adapter: str = ""
    model: str = ""
    base_url: str = ""
    key_set: bool = False
    settings_readable: bool = True

    @property
    def can_send(self) -> bool:
        """Whether an adapter and model are named, allowing outbound work."""
        return bool(self.adapter and self.model)

    def as_dict(self) -> dict[str, Any]:
        return {
            "locale": self.locale,
            "currency": self.currency,
            "adapter": self.adapter,
            "model": self.model,
            "base_url": self.base_url,
            "key_set": self.key_set,
            "can_send": self.can_send,
            "settings_readable": self.settings_readable,
        }


@dataclass(frozen=True)
class Proposal:
    """One reviewed change, and the digest a yes has to name.

    `sends` is whether saying yes to this makes bytes able to leave. It is the
    one fact that decides how the proposal is presented, and it is decided here
    rather than inferred from which fields moved."""

    kind: str
    changes: dict[str, str]
    sends: bool
    digest: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "digest", digest_of(self.kind, self.changes))

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            # The key never travels, and there is no branch here that could
            # carry it: the changes a proposal describes name whether a key
            # would be set, never what it is.
            "changes": dict(self.changes),
            "sends": self.sends,
            "digest": self.digest,
        }


def digest_of(kind: str, changes: dict[str, str]) -> str:
    """The name of one exact proposal.

    Over the kind and the changes, canonically, so two proposals describing the
    same thing have one name and a proposal that moved has another."""
    body = json.dumps({"kind": kind, "changes": dict(sorted(changes.items()))},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()[:16]


# ------------------------------------------------------------------ the key


@dataclass(frozen=True)
class KeyRecord:
    """The key's environment name and whether a value is held there."""

    variable: str
    held: bool


def key_store(key: str = "", variable: str = "",
              commit: Callable[[], None] | None = None) -> KeyRecord:
    """Read key presence, or store a key owner-only and put it in force.

    Returns the environment name and presence only; never the secret value.
    If ``commit`` fails, the credential write is rolled back.
    """
    if not key.strip():
        # An explicit environment name remains in force for this process.
        selected = variable.strip() or os.environ.get(KEY_ENV_VAR) or KEY_NAME
        return KeyRecord(selected, bool(os.environ.get(selected)))
    lines = []
    previous_text: str | None = None
    previous_mode: int | None = None
    previous_key: str | None = None
    try:
        if SECRETS_FILE.exists():
            previous_text = SECRETS_FILE.read_text(encoding="utf-8")
            previous_mode = stat.S_IMODE(SECRETS_FILE.stat().st_mode)
            for line in previous_text.splitlines():
                if line.strip().startswith(f"{KEY_NAME}="):
                    previous_key = line.partition("=")[2]
                else:
                    lines.append(line)
    except OSError as exc:
        raise ConfigurationError(UNWRITABLE) from exc
    lines.append(f"{KEY_NAME}={key.strip()}")
    try:
        CONFIG_HOME.mkdir(parents=True, exist_ok=True)
        handle = os.open(str(SECRETS_FILE), os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                         stat.S_IRUSR | stat.S_IWUSR)
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write("\n".join(lines) + "\n")
        os.chmod(SECRETS_FILE, stat.S_IRUSR | stat.S_IWUSR)
    except OSError as exc:
        raise ConfigurationError(UNWRITABLE) from exc
    previous_environment = os.environ.get(KEY_NAME)
    activate = (KEY_NAME not in _EXPLICIT_ENVIRONMENT
                and (previous_environment is None
                     or previous_environment == previous_key))
    if activate:
        os.environ[KEY_NAME] = key.strip()
    try:
        if commit is not None:
            commit()
    except Exception:
        try:
            if previous_text is None:
                SECRETS_FILE.unlink(missing_ok=True)
            else:
                handle = os.open(str(SECRETS_FILE),
                                 os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                                 previous_mode or stat.S_IRUSR | stat.S_IWUSR)
                with os.fdopen(handle, "w", encoding="utf-8") as out:
                    out.write(previous_text)
                os.chmod(SECRETS_FILE,
                         previous_mode or stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            log.exception("the credential write could not be rolled back")
        if activate:
            if previous_environment is None:
                os.environ.pop(KEY_NAME, None)
            else:
                os.environ[KEY_NAME] = previous_environment
        raise
    return KeyRecord(KEY_NAME, True)


# ------------------------------------------------------------------ reading


@dataclass(frozen=True)
class Stored:
    """Stored settings and whether an existing settings file was readable."""

    settings: dict[str, Any]
    readable: bool = True


def current() -> Configuration:
    """What is in force right now, environment first.

    The environment wins over the file for the same reason it wins over the
    `.env`: an explicit export is somebody saying so at the point of running,
    and a stored setting must never quietly override it."""
    stored = _stored()
    settings = stored.settings
    return Configuration(
        locale=os.environ.get(LOCALE_VAR) or settings.get("locale", "") or "en-US",
        currency=os.environ.get(CURRENCY_VAR) or settings.get("currency", "") or "USD",
        adapter=os.environ.get(ADAPTER_VAR) or settings.get("adapter", ""),
        model=os.environ.get(MODEL_VAR) or settings.get("model", ""),
        base_url=os.environ.get(BASE_URL_VAR) or settings.get("base_url", ""),
        key_set=key_store().held,
        settings_readable=stored.readable,
    )


def _stored() -> Stored:
    """Read settings without modifying an unreadable file."""
    try:
        held = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return Stored({})
    except (OSError, json.JSONDecodeError):
        log.warning("the settings at %s could not be read", SETTINGS_FILE)
        return Stored({}, readable=False)
    if not isinstance(held, dict):
        log.warning("the settings at %s hold no settings", SETTINGS_FILE)
        return Stored({}, readable=False)
    return Stored(held)


# ---------------------------------------------------------------- proposing


def propose_presentation(locale: str = "", currency: str = "") -> Proposal:
    """What would change about how figures are written.

    This builder has nowhere to put a model, an adapter, a base url or a key.
    That is the carve-out: not a check that a later edit could relax, but a
    signature with no room in it. Nothing on this path can reach the reader's
    model edge, because nothing on it names one.
    """
    held = current()
    changes: dict[str, str] = {}
    if locale.strip() and locale.strip() != held.locale:
        changes["locale"] = _checked_locale(locale.strip())
    if currency.strip() and currency.strip().upper() != held.currency:
        changes["currency"] = _checked_currency(currency.strip())
    return Proposal("presentation", changes, sends=False)


def propose_model(adapter: str = "", model: str = "", base_url: str = "",
                  key: str = "", key_action: str = "") -> Proposal:
    """What would change about which model may be reached.

    Naming a model is what makes bytes able to leave, so this proposal always
    declares that it sends — including the one that names none, which stops
    anything being able to leave and is exactly as much a change to that
    permission.
    """
    held = current()
    adapter = adapter.strip()
    model = model.strip()
    key_action = key_action.strip()
    if not adapter and not model:
        # Naming nothing is how a person takes the permission back. It is a
        # change to the same thing, so it travels on the same path.
        return Proposal("model", {"adapter": "", "model": "", "base_url": ""},
                        sends=True)
    if adapter not in ADAPTERS:
        raise ConfigurationError(UNKNOWN_ADAPTER)
    if not model or any(alias in model.lower() for alias in _UNPINNED):
        raise ConfigurationError(UNPINNED_MODEL)
    key_will_be_set = bool(key.strip()) or key_action == "set"
    key_is_not_needed = key_action == "none"
    if not key_will_be_set and not key_is_not_needed and not held.key_set:
        raise ConfigurationError(MISSING_KEY)
    changes = {"adapter": adapter, "model": model,
               "base_url": base_url.strip()}
    if key_will_be_set:
        # Whether a key would be set, never what it is. The digest a yes names
        # therefore covers the fact of a key and not its value, which is what
        # keeps the secret out of every reply this proposal appears in.
        changes["key"] = "set"
    elif key_is_not_needed:
        # This value is explicit input and is never inferred from the address.
        changes["key"] = "not needed"
    return Proposal("model", changes, sends=True)


def _checked_locale(locale: str) -> str:
    from vivacore.verify.normalize import known_language_tags

    canonical = locale.replace("_", "-")
    parts = canonical.split("-")
    shaped = (len(parts) <= 2 and all(parts)
              and (len(parts) == 1 or len(parts[1]) in (2, 3)))
    if parts[0].lower() not in known_language_tags() or not shaped:
        raise ConfigurationError(UNKNOWN_LOCALE)
    return canonical


def _checked_currency(currency: str) -> str:
    upper = currency.upper()
    if len(upper) != 3 or not upper.isalpha():
        raise ConfigurationError(UNKNOWN_CURRENCY)
    return upper


# ----------------------------------------------------------------- applying


def apply(proposal: Proposal, digest: str, key: str = "") -> Configuration:
    """Apply exactly the proposal that was shown, or nothing.

    ``digest`` is what the person said yes to. A yes that names something else
    applies nothing, because a person who was shown one thing and confirmed
    while another was in flight has not agreed to what would happen.

    The key is handed in here rather than carried on the proposal, so the
    secret exists in one call and never in a reply, a log line or a digest.
    """
    if digest != proposal.digest:
        raise ConfigurationError(NOT_THE_PROPOSAL)
    previous = _stored().settings
    stored = dict(previous)
    for name, value in proposal.changes.items():
        if name == "key":
            continue
        stored[name] = value
    key_change = proposal.changes.get("key", "")
    if key_change == "set" and not key.strip():
        raise ConfigurationError(MISSING_KEY)
    if key_change == "set":
        # Persist the store-selected name only when this proposal writes a key.
        stored[KEY_ENV_FIELD] = KEY_NAME
    elif key_change == "not needed":
        # `none` selects the existing keyless adapter path without deleting a
        # stored credential.
        stored[KEY_ENV_FIELD] = "none"
    if key_change == "set":
        key_store(key, commit=lambda: _write(stored))
    else:
        _write(stored)
    _put_in_force(stored, previous)
    return current()


def _write(stored: dict[str, Any]) -> None:
    try:
        CONFIG_HOME.mkdir(parents=True, exist_ok=True)
        partial = SETTINGS_FILE.with_name(SETTINGS_FILE.name + ".partial")
        partial.write_text(json.dumps(stored, indent=2, sort_keys=True) + "\n",
                           encoding="utf-8")
        partial.replace(SETTINGS_FILE)
    except OSError as exc:
        raise ConfigurationError(UNWRITABLE) from exc


def _where_a_key_is_read_from(stored: dict[str, Any]) -> str:
    """Return the stored key name, falling back to the credential store."""
    return key_store(variable=str(stored.get(KEY_ENV_FIELD, ""))).variable


def _is_explicit(variable: str, previous: str) -> bool:
    """Whether a process value came from outside stored settings."""
    if variable in _EXPLICIT_ENVIRONMENT:
        return True
    return variable in os.environ and os.environ[variable] != previous


def _put_in_force(stored: dict[str, Any], previous: dict[str, Any]) -> None:
    """Make what was just written true for the process that wrote it.

    A setting a person applied and that takes effect on the next launch is a
    setting that did not take effect, and there is no screen on which that
    reads as anything but a control that did not work."""
    for name, variable in _IN_FORCE:
        before = str(previous.get(name, "")).strip()
        if _is_explicit(variable, before):
            continue
        value = str(stored.get(name, "")).strip()
        if value:
            os.environ[variable] = value
        else:
            os.environ.pop(variable, None)
    # Model changes that do not mention a key preserve the current key route.
    before = _where_a_key_is_read_from(previous)
    if not _is_explicit(KEY_ENV_VAR, before):
        os.environ[KEY_ENV_VAR] = _where_a_key_is_read_from(stored)


# ---------------------------------------------------------------- starting up


def put_stored_in_force() -> None:
    """Load stored settings without overriding explicit environment values."""
    from .env import env_file, load_dotenv

    present_before_file = _present_environment()
    source = env_file()
    if source is not None:
        load_dotenv(source)
    _EXPLICIT_ENVIRONMENT.update(present_before_file)
    present_after_file = _present_environment()
    if (source is not None and source.resolve() == SECRETS_FILE.resolve()
            and KEY_NAME not in present_before_file):
        present_after_file.discard(KEY_NAME)
    _EXPLICIT_ENVIRONMENT.update(present_after_file)
    stored = _stored().settings
    for name, variable in _IN_FORCE:
        value = str(stored.get(name, "")).strip()
        if value:
            os.environ.setdefault(variable, value)
    # The key's environment name follows the same precedence as routing.
    os.environ.setdefault(KEY_ENV_VAR, _where_a_key_is_read_from(stored))
