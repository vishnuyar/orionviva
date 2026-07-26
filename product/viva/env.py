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

    Why this exists (2026-07-26). `rebuild` defaulted to "US" while `web`,
    `debug_claim` and `debug_read` all defaulted to "en-US". "US" is not a
    language tag, so the amount parser had no decimal convention for it and
    refused every three-decimal figure as ambiguous.

    The visible consequence: two brokerage statements parsed perfectly under
    `debug_claim` and parked under `rebuild`, on the same code and the same
    stored reply. Chasing that produced a "unit-quantity defect" that never
    existed, and left real holdings out of a net-worth figure for days.

    A setting that four programs each default separately is not a default, it is
    four defaults. One accessor, one value, and an unrecognised tag stops the run
    with the list of valid ones rather than quietly becoming a stricter parser."""
    import os

    from vivacore.verify.normalize import known_language_tags

    locale = os.environ.get("VIVA_LOCALE", "en-US").strip()
    if locale.split("-")[0].lower() not in known_language_tags():
        raise SystemExit(
            f"VIVA_LOCALE={locale!r} names no decimal convention I know.\n"
            f"  Its language part must be one of: "
            f"{', '.join(known_language_tags())}\n"
            f"  (e.g. 'en-US', 'en-IN', 'de-DE'.) Left unrecognised, every\n"
            f"  three-decimal figure would be refused as ambiguous and the\n"
            f"  documents containing them would park for no visible reason.")
    return locale


def currency_from_env() -> str:
    import os
    return os.environ.get("VIVA_CURRENCY", "USD").strip() or "USD"
