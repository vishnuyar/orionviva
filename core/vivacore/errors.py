"""Shared errors."""

from __future__ import annotations


class ConfigError(Exception):
    """A configuration problem the caller must fix. The message is the fix."""
