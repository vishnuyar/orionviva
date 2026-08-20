"""Load a local ``.env`` into the process environment, and read the locale.

The vault passphrase and model keys live in ``.env`` (git-ignored, never
committed). Existing environment variables always win: an explicit ``export``
overrides the file, and a secret already in the environment is never clobbered.

**Where the file is looked for is a security property, not a convenience.** This
used to default to the relative path ``.env``, which resolves against whatever
directory the process was started in. A ``.env`` left in a cloned repository, an
unpacked starter kit or a shared vault directory was therefore configuration: it
could set the model base URL and ``HTTPS_PROXY``, and every page image of every
statement would be posted to a host of its author's choosing with the real API
key in the header — silently, with no line naming the file or the host. The
search order below is fixed, does not include the working directory, and the
source-tree entry is found by walking up from *this file* rather than from the
cwd, so no caller's location can introduce a new candidate.
"""

from __future__ import annotations

import logging
import os
import pathlib

log = logging.getLogger(__name__)

CONFIG_HOME = pathlib.Path.home() / ".orionviva"

# Marks the root of an OrionViva source tree. Tracked, and it sits beside the
# `.env` it is an example of, so finding one is finding where the other belongs.
_TREE_MARKER = ".env.example"


def _source_tree_root() -> pathlib.Path | None:
    """The source tree this module was imported from, or None once installed."""
    for parent in pathlib.Path(__file__).resolve().parents:
        if (parent / _TREE_MARKER).is_file():
            return parent
    return None


def env_file() -> pathlib.Path | None:
    """The one `.env` this process will read, or None when there is none.

    In order: ``VIVA_ENV_FILE`` if it names one; then ``~/.orionviva/.env``,
    which is where a packaged install keeps it; then the root of the source tree
    this module lives in. The working directory is never consulted."""
    explicit = os.environ.get("VIVA_ENV_FILE", "").strip()
    candidates = [pathlib.Path(explicit).expanduser()] if explicit else []
    candidates.append(CONFIG_HOME / ".env")
    # Beside the installed package, which is where a source checkout keeps it
    # today: `product/.env`, next to `product/viva/`. Derived from this file's
    # own location, so it names one directory no matter who calls it.
    candidates.append(pathlib.Path(__file__).resolve().parents[1] / ".env")
    root = _source_tree_root()
    if root is not None:
        candidates.append(root / ".env")
    return next((c for c in candidates if c.is_file()), None)


def load_dotenv(path: str | os.PathLike | None = None) -> bool:
    """Populate os.environ from the `.env` this process reads. True if loaded.

    ``path`` names a file explicitly — the bench harness does this — and is
    taken as given. With no argument the fixed search order in `env_file` is
    used; the working directory is not part of it."""
    p = pathlib.Path(path) if path is not None else env_file()
    if p is None or not p.exists():
        return False
    # Which file configured this run is worth saying out loud: it decides where
    # documents are sent.
    log.info("configuration loaded from %s", p)
    for line in p.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'").strip('"'))
    return True


def jurisdiction_from_env() -> str:
    """The region the vault's locale names, or '' when it names none.

    The ONE place this is derived. Two readers of the same schema pack that
    resolved it differently would ask for a fact through one door and refuse it
    at the other."""
    parts = locale_from_env().split("-")
    return parts[1] if len(parts) > 1 else ""


def locale_from_env() -> str:
    """The configured locale, canonicalized — the one accessor every entry point
    uses. ``VIVA_LOCALE`` defaults to ``en-US``.

    Raises ``SystemExit``, listing the valid language tags, when the language
    part is unknown or the region part is not a 2- or 3-letter code."""
    import os

    from vivacore.verify.normalize import known_language_tags

    locale = os.environ.get("VIVA_LOCALE", "en-US").strip()
    # The region subtag decides the date convention. `_` becomes `-` and the
    # language part is compared case-insensitively, so `en_us` and `en-US` name
    # one convention; anything else about the shape stops the run.
    canonical = locale.replace("_", "-")
    parts = canonical.split("-")
    shape_ok = (len(parts) <= 2 and all(parts)
                and (len(parts) == 1 or len(parts[1]) in (2, 3)))
    if parts[0].lower() not in known_language_tags() or not shape_ok:
        raise SystemExit(
            f"VIVA_LOCALE={locale!r} names no decimal convention I know.\n"
            f"  Its language part must be one of: "
            f"{', '.join(known_language_tags())}\n"
            f"  and its region, when present, must be a 2- or 3-letter code.\n"
            f"  (e.g. 'en-US', 'en-IN', 'de-DE'.) Left unrecognised, every\n"
            f"  three-decimal figure would be refused as ambiguous and the\n"
            f"  documents containing them would park for no visible reason.")
    return canonical


def currency_from_env() -> str:
    import os
    return os.environ.get("VIVA_CURRENCY", "USD").strip() or "USD"
