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
