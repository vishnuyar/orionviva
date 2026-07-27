"""Load a local ``.env`` into the process environment.

The vault passphrase and model keys live in ``.env`` (git-ignored, never
committed). This loads them so you can just run the surface. Existing
environment variables always win — an explicit ``export`` overrides the file,
and a secret already in the environment is never clobbered.
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


def locale_from_env() -> str:
    """The configured locale, validated — the single source for every entry point.

    An unrecognised language tag stops the run and lists the valid ones: a parser
    with no decimal convention for the tag refuses every three-decimal figure as
    ambiguous, and the documents containing them park for no visible reason."""
    import os

    from vivacore.verify.normalize import known_language_tags

    locale = os.environ.get("VIVA_LOCALE", "en-US").strip()
    # The region subtag decides the date convention, so a typo in it is a silent
    # wrong answer rather than a stricter parser: 'en-us' and 'en-US' must not
    # name different conventions, and an unrecognised shape must stop the run.
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
