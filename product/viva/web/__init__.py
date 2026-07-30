"""The local web surface — the person's window into their data.

A dashboard (total, accounts, coverage), review and rulings on held statements,
an account drill-down, and document upload. Provenance is carried in every
payload but rendered only where it is asked for.

`server` holds the HTTP plumbing, `service` the logic behind it.
"""

from .server import make_handler, serve

__all__ = ["serve", "make_handler"]
