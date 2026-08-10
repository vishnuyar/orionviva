"""Print a vault's category vocabulary — labels, subcategories, tags, aliases.

    VIVA_VAULT_DIR=<vault> python -m viva.debug.categories

Prints every category label with what it is worth, the subcategory vocabulary
enrichment has written, what each subcategory is worth under its own category
with the remainder no subcategory names, spending by tag against total spending
and the untagged remainder, and the aliases already folded together. It does not guess which
labels mean the same thing; that is recorded once as a ruling and applied on the
read side:

    from viva.ingest import rule_category_same_as
    rule_category_same_as(vault.ledger, "playing poker", "poker")

Read-only, no model call. A recorded merge is retroactive and is reversed by
appending.
"""

from __future__ import annotations

import os
import pathlib
from decimal import Decimal


def report(proj) -> str:
    spending = proj.spending_by_category()
    aliases = proj.category_aliases()
    labels = proj.known_categories()
    subs = proj.known_subcategories()

    out = [f"{len(labels)} category label(s) · {len(subs)} subcategory label(s) "
           f"· {len(proj.known_tags())} tag(s)", ""]
    if spending:
        out.append("  what each label is worth")
        for label, amount in sorted(spending.items(), key=lambda kv: -kv[1]):
            out.append(f"    {label[:34]:34} {amount:>14,.2f}")
        out.append("")
    if subs:
        out += ["  the finer vocabulary (enrichment writes these)", ""]
        out.append("    " + ", ".join(subs))
        out.append("")
    tree = proj.spending_by_category_then_subcategory()
    finer = {c: w for c, w in tree.items() if any(s for s in w)}
    if finer:
        out += ["  what each subcategory is worth, under its category", ""]
        for label, within in sorted(finer.items(),
                                    key=lambda kv: -sum(kv[1].values())):
            out.append(f"    {label[:34]:34} {sum(within.values()):>14,.2f}")
            for sub, amount in sorted(within.items(), key=lambda kv: -kv[1]):
                if not sub:
                    continue
                out.append(f"      {sub[:32]:32} {amount:>14,.2f}")
            # Named, never dropped: a category's subcategories sum to less than
            # the category itself until every movement under it is named, and a
            # total that quietly did not add up would read as a discrepancy.
            unassigned = within.get("", Decimal("0"))
            if unassigned:
                out.append(f"      {'— of which unassigned':32} "
                           f"{unassigned:>14,.2f}")
        out.append("")
    tags = proj.known_tags()
    by_tag = proj.spending_by_tag()
    if tags:
        out += ["  tags — an OVERLAY, not a partition", ""]
        for tag, amount in sorted(by_tag["by_tag"].items(), key=lambda kv: -kv[1]):
            out.append(f"    {tag[:34]:34} {amount:>14,.2f}")
        out += ["",
                f"    these overlap: they sum to "
                f"{sum(by_tag['by_tag'].values()):,.2f} against total spending of "
                f"{by_tag['total']:,.2f},",
                f"    and {by_tag['untagged']:,.2f} carries no tag at all. That is "
                "correct, not a discrepancy —",
                "    a tag answers 'how much on the Japan trip', which is a "
                "different question",
                "    from 'where did my money go'. Only the category report "
                "closes.", ""]

    if aliases:
        out += ["  already folded together"]
        for dup, canonical in sorted(aliases.items()):
            out.append(f"    {dup}  →  {canonical}")
        out.append("")
    out += [
        "  Two labels meaning one thing split a total in half and raise nothing.",
        "  This tool deliberately does NOT guess which pairs those are — it shows",
        "  you the vocabulary and records your ruling, because a similarity",
        "  threshold is a keyword list with decimals, and one that recomputes",
        "  each run would merge and un-merge categories behind your back.",
    ]
    return "\n".join(out)


def main() -> None:
    from ..env import load_dotenv
    from ..vault import Vault

    load_dotenv()
    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (or put it in .env).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR", os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")
    vault = Vault.open(vault_dir, passphrase)
    print(f"vault: {vault_dir}\n")
    print(report(vault.ledger.projection()))


if __name__ == "__main__":
    main()
