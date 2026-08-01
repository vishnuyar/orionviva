"""Load a local ``.env`` into the process environment, and read the locale.

The vault passphrase and model keys live in ``.env`` (git-ignored, never
committed). Existing environment variables always win: an explicit ``export``
overrides the file, and a secret already in the environment is never clobbered.
"""

from __future__ import annotations

import os
import pathlib


def load_dotenv(path: str = ".env") -> bool:
    """Populate os.environ from a .env file if present. Returns True if loaded."""
    p = pathlib.Path(path)
    if not p.exists():
        return False
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
