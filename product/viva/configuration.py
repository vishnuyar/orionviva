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
    it. What a screen may know is whether one is set, which is what decides
    whether a model can be reached at all."""

    locale: str
    currency: str
    adapter: str = ""
    model: str = ""
    base_url: str = ""
    key_set: bool = False

    @property
    def can_send(self) -> bool:
        """Whether anything can leave this machine as things stand.

        The same question :func:`viva.ingest.reader.build_reader` asks, asked
        where a person can be told the answer."""
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


# ------------------------------------------------------------------ reading


def current() -> Configuration:
    """What is in force right now, environment first.

    The environment wins over the file for the same reason it wins over the
    `.env`: an explicit export is somebody saying so at the point of running,
    and a stored setting must never quietly override it."""
    stored = _stored()
    return Configuration(
        locale=os.environ.get(LOCALE_VAR) or stored.get("locale", "") or "en-US",
        currency=os.environ.get(CURRENCY_VAR) or stored.get("currency", "") or "USD",
        adapter=os.environ.get(ADAPTER_VAR) or stored.get("adapter", ""),
        model=os.environ.get(MODEL_VAR) or stored.get("model", ""),
        base_url=os.environ.get(BASE_URL_VAR) or stored.get("base_url", ""),
        key_set=bool(os.environ.get(os.environ.get(KEY_ENV_VAR, KEY_NAME))),
    )


def _stored() -> dict[str, Any]:
    try:
        held = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return held if isinstance(held, dict) else {}


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
                  key: str = "") -> Proposal:
    """What would change about which model may be reached.

    Naming a model is what makes bytes able to leave, so this proposal always
    declares that it sends — including the one that names none, which stops
    anything being able to leave and is exactly as much a change to that
    permission.
    """
    held = current()
    adapter = adapter.strip()
    model = model.strip()
    if not adapter and not model:
        # Naming nothing is how a person takes the permission back. It is a
        # change to the same thing, so it travels on the same path.
        return Proposal("model", {"adapter": "", "model": "", "base_url": ""},
                        sends=True)
    if adapter not in ADAPTERS:
        raise ConfigurationError(UNKNOWN_ADAPTER)
    if not model or any(alias in model.lower() for alias in _UNPINNED):
        raise ConfigurationError(UNPINNED_MODEL)
    if not key.strip() and not held.key_set:
        raise ConfigurationError(MISSING_KEY)
    changes = {"adapter": adapter, "model": model,
               "base_url": base_url.strip()}
    if key.strip():
        # Whether a key would be set, never what it is. The digest a yes names
        # therefore covers the fact of a key and not its value, which is what
        # keeps the secret out of every reply this proposal appears in.
        changes["key"] = "set"
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
    stored = _stored()
    for name, value in proposal.changes.items():
        if name == "key":
            continue
        stored[name] = value
    _write(stored)
    if proposal.changes.get("key") == "set" or key.strip():
        _write_key(key)
    _put_in_force(stored, key)
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


def _write_key(key: str) -> None:
    """Put the key where the engine already looks, readable by nobody else.

    The file is created with its permissions already narrow rather than
    narrowed afterwards: a key that is world-readable for even the moment
    between writing and chmod is a key that leaked."""
    if not key.strip():
        return
    lines = []
    try:
        if SECRETS_FILE.exists():
            lines = [line for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines()
                     if not line.strip().startswith(f"{KEY_NAME}=")]
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


def _put_in_force(stored: dict[str, Any], key: str) -> None:
    """Make what was just written true for the process that wrote it.

    A setting a person applied and that takes effect on the next launch is a
    setting that did not take effect, and there is no screen on which that
    reads as anything but a control that did not work."""
    for name, variable in (("locale", LOCALE_VAR), ("currency", CURRENCY_VAR),
                           ("adapter", ADAPTER_VAR), ("model", MODEL_VAR),
                           ("base_url", BASE_URL_VAR)):
        value = str(stored.get(name, ""))
        if value:
            os.environ[variable] = value
        else:
            os.environ.pop(variable, None)
    os.environ[KEY_ENV_VAR] = KEY_NAME
    if key.strip():
        os.environ[KEY_NAME] = key.strip()
