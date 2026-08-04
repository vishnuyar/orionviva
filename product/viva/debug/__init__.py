"""Read-only diagnostics: tools that explain what the product did.

Everything in this package obeys one rule — it opens a vault, prints to a
terminal, and changes nothing. No event is appended, no model is called, no
file is written. That is what separates these from the operator tools that
live at the top of `viva` (`rebuild`, `rescan`, `reingest`,
`reset_categorization`), which exist precisely to change a vault and keep
their power visible by staying where it can be seen.

Each module runs as a command:

    PYTHONPATH=../core:../merchant:. python3 -m viva.debug.vault
    PYTHONPATH=../core:../merchant:. python3 -m viva.debug.speak 1

They read `./.env` for `VIVA_PASSPHRASE` and `VIVA_VAULT_DIR`, so they run
from `product/`.
"""
