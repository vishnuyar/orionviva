"""Logging setup — verbose by design while we debug the real pipeline.

Library modules only ``logging.getLogger(__name__)`` and emit; they never
configure handlers. The entrypoints (the surface, the debug tools) call
``configure()`` — so tests stay silent (no handler installed) and real runs are
chatty. Turn detail all the way up with ``VIVA_LOG_LEVEL=DEBUG``.
"""

from __future__ import annotations

import logging
import os


def configure(default: str = "INFO") -> None:
    """Install a console handler at VIVA_LOG_LEVEL (default INFO). Idempotent."""
    level_name = os.environ.get("VIVA_LOG_LEVEL", default).upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-5s %(name)-24s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("viva").setLevel(level)
