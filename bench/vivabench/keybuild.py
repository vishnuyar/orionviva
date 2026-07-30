"""Answer-key construction: two model families draft, agreement auto-verifies,
disagreements go to human audit, then freeze + hash.

Two independent model families extract the same document. Where they agree a
value is accepted with ``verified_by="cross-model"``; where they disagree it goes
to an audit worksheet for a person to rule on. `freeze` returns the key's
canonical hash, which a later run cites to show it used the same key.

`merge_drafts`, `apply_audit` and `freeze` make no model calls; only `draft_key`
needs the network.

Design rationale: docs/benchmark-harness-design.md
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from vivacore.claims import AnswerKey, Claim, KeyEntry, parse_claims
from .config import BenchConfig, Document
from .corpus import render_pages
from vivacore.models import adapter_for
from .runner import extract_by_page
from vivacore.verify.match import match_amount, match_date, match_text
from vivacore.verify.normalize import RULES_VERSION


@dataclass
class DraftEntry:
    type: str
    label: str
    values: list[str]         # one per drafting model (as printed)
    agree: bool
    resolved: str | None = None   # human ruling, if any


def _agree(entry_type: str, a: str, b: str, locale: str, currency: str) -> bool:
    if entry_type == "amount":
        return bool(match_amount(a, b, locale, currency).correct)
    if entry_type == "date":
        return bool(match_date(a, b, locale).correct)
    return bool(match_text(a, b).correct)


def draft_key(
    doc: Document,
    config: BenchConfig,
    drafter_names: list[str],
    page_cache: Path,
    log=print,
) -> tuple[AnswerKey, list[DraftEntry]]:
    """Run the drafter models and merge their claims, as `merge_drafts` returns.

    Needs the network and the candidates' API keys. Raises ValueError with fewer
    than two drafters."""
    if len(drafter_names) < 2:
        raise ValueError("Key drafting needs at least two different model families.")
    pages = render_pages(doc, page_cache)
    from .corpus import file_sha256

    extractions: dict[str, list[Claim]] = {}
    for name in drafter_names:
        cand = config.candidate(name)
        log(f"  drafting with {name} ({cand.model}) ...")
        _, fields = extract_by_page(adapter_for(cand), pages, log)
        claims, err = parse_claims(fields["text"])
        if err:
            log(f"    WARNING: {name} output did not parse ({err}); skipping its draft")
            claims = []
        # A truncated or unparsed page contributed no claims, so the draft is
        # incomplete for that page. Warn rather than fail: the entries that did
        # come through are still usable, and the gap is visible in the log.
        if fields["pages_truncated"]:
            log(f"    WARNING: {name} was TRUNCATED on pages "
                f"{fields['pages_truncated']} — its draft is incomplete.")
        if fields["pages_unparsed"]:
            log(f"    WARNING: {name} output unparsable on pages "
                f"{fields['pages_unparsed']} — those pages contributed nothing.")
        extractions[name] = claims

    return merge_drafts(doc, extractions, drafter_names, log)


def _norm_label(s: str) -> str:
    import re
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def merge_drafts(
    doc: Document,
    extractions: dict[str, list[Claim]],
    drafter_names: list[str],
    log=print,
) -> tuple[AnswerKey, list[DraftEntry]]:
    """Merge two or more drafters' claims into a draft key.

    Claims are grouped by (type, normalized label). An entry reaches the key only
    when every drafter produced that claim and their values agree under `_agree`,
    stamped ``verified_by="cross-model"``; everything else comes back as a
    DraftEntry with ``agree=False`` for audit.

    Returns `(key, drafts)`: an unfrozen AnswerKey and one DraftEntry per distinct
    claim, ordered by (type, label). Makes no model calls, so `extractions` may
    come from a live run or from the raw log (``draft-key --from-log``).
    """
    from .corpus import file_sha256

    indexed: dict[tuple[str, str], dict[str, str]] = defaultdict(dict)
    for name, claims in extractions.items():
        for c in claims:
            indexed[(c.type, _norm_label(c.label))].setdefault(name, c.value_raw)

    drafts: list[DraftEntry] = []
    entries: list[KeyEntry] = []
    for (ctype, nlabel), by_model in sorted(indexed.items()):
        values = [by_model[n] for n in drafter_names if n in by_model]
        present_in_all = len(values) == len(drafter_names)
        agree = present_in_all and all(
            _agree(ctype, values[0], v, doc.locale, doc.currency) for v in values[1:]
        )
        label = next(
            (c.label for c in extractions[drafter_names[0]]
             if (c.type, _norm_label(c.label)) == (ctype, nlabel)),
            nlabel,
        )
        drafts.append(DraftEntry(type=ctype, label=label, values=values, agree=agree))
        if agree:
            entries.append(KeyEntry(
                type=ctype, label=label, value_raw=values[0],
                locale=doc.locale, currency=doc.currency,
                verified_by="cross-model",
            ))

    key = AnswerKey(
        doc_id=doc.id, doc_sha256=file_sha256(doc.file),
        locale=doc.locale, currency=doc.currency,
        entries=entries, frozen=False, rules_version=RULES_VERSION,
    )
    agreed = sum(1 for d in drafts if d.agree)
    log(f"  {len(drafts)} distinct claims; {agreed} auto-corroborated, "
        f"{len(drafts) - agreed} need audit.")
    return key, drafts


def apply_audit(key: AnswerKey, drafts: list[DraftEntry]) -> AnswerKey:
    """Fold human-resolved disagreements (DraftEntry.resolved set) into the key."""
    for d in drafts:
        if not d.agree and d.resolved is not None and d.resolved != "":
            key.entries.append(KeyEntry(
                type=d.type, label=d.label, value_raw=d.resolved,
                locale=key.locale, currency=key.currency, verified_by="human",
            ))
    return key


def freeze(key: AnswerKey) -> tuple[AnswerKey, str]:
    """Mark the key frozen in place and return `(key, canonical_hash)`."""
    key.frozen = True
    return key, key.canonical_hash()
