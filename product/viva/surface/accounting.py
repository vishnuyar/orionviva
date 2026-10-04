"""Formatted financial statements with distinct measurement and meaning evidence."""
from __future__ import annotations

from copy import deepcopy

from .. import render
from ..ledger.accounting import financial_statements


def accounting(projection, locale: str, today: str, *, start: str = "", end: str = "") -> dict:
    """Compose reports without changing the accounting projection's arithmetic."""
    result = deepcopy(financial_statements(projection, start=start, end=end or today, as_of=end or today))
    documents = set(projection.captured_docs()) if hasattr(projection, "captured_docs") else set()
    for report in (result['balance_sheet'], result['profit_loss']):
        report['display_by_currency'] = {
            currency: {key: str(render.money(value, currency, locale=locale))
                       for key, value in totals.items()}
            for currency, totals in report['by_currency'].items()}
        for row in report.get('lines', []) + report.get('unresolved_components', []):
            row['display'] = str(render.money(row['amount'], row['currency'], locale=locale))
            measurement = row.get('amount_evidence') or {}
            meaning = row.get('classification_evidence') or {}
            references = list(meaning.get('source_refs') or []) + list(measurement.get('source_refs') or [])
            references += [row.get('proves', ''), (measurement.get('provenance') or {}).get('doc_id', '')]
            references += [(related.get('provenance') or {}).get('doc_id', '')
                           for related in measurement.get('related_sources') or []]
            related_records = (list(measurement.get('sources') or [])
                               + list(meaning.get('related_sources') or [])
                               + list(row.get('supporting_components') or []))
            references += [(related.get('provenance') or {}).get('doc_id', '')
                           for related in related_records]
            existing = meaning.get('existing_treatment') or {}
            references += list(existing.get('source_refs') or [])
            for source in meaning.get('sources') or []:
                references += list(source.get('source_refs') or [])
            for component in row.get('supporting_components') or []:
                component['display'] = str(render.money(component['amount'], row['currency'], locale=locale))
            row['document_ids'] = sorted({reference for reference in references
                                          if reference in documents})
    for row in result['profit_loss'].get('hierarchy', []):
        row['display'] = str(render.money(row['amount'], row['currency'], locale=locale))
    def format_node(node, currency):
        node["display"] = str(render.money(node["amount"], currency, locale=locale))
        for child in node.get("children", []):
            format_node(child, currency)
    for group in result["profit_loss"].get("hierarchy_tree", []):
        for root in group["roots"]:
            format_node(root, group["currency"])
    return result
