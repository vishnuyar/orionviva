"""The local web surface — the person's window into their data.

A calm dashboard (total, accounts, coverage), the ability to review and rule on
held statements, drill into an account, and upload new documents. Provenance is
built in but kept quiet — surfaced only where it helps (reviewing a held item),
never as the headline.
"""

from .server import make_handler, serve

__all__ = ["serve", "make_handler"]
