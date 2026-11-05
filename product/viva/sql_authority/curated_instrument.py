"""Typed unsupported derivations over independently retained curated readings."""
import json

from ..ingest import instrument_read
from ..ingest.instrument_read import InstrumentReadFacts, validate_sources
from ..ingest.instrument_contracts import ContractError
from .curated_instrument_contract import PROFILE, INTERPRETATION_KIND, LEXICAL_SCOPE
from .store import canonical


def interpretation(store, receipt):
    from .curated import instrument_inputs
    inputs = instrument_inputs(store, receipt, json.loads(receipt["body"]))
    admitted, profile = inputs["admitted"], inputs["profile"]
    locale, currency = admitted["locale"], admitted["currency"]
    facts = None
    disposition, reason = "unavailable", "parser_input_unavailable"
    if type(currency) is str and currency:
        disposition, reason = "unavailable", "parser_refused"
        try:
            parsed, error = instrument_read.parser_for(inputs["doc_type"], source_contract=profile.instrument_source_contract,
                                       page_count=inputs["page_count"])(inputs["text"], receipt["doc_id"], locale, currency)
            if parsed is not None and not error:
                validate_sources(parsed.payload, receipt["doc_id"], inputs["page_count"])
                wrapped = InstrumentReadFacts(receipt["doc_id"], inputs["doc_type"], None,
                                              parsed.payload, currency, dict(admitted["acquisition"]))
                facts = InstrumentReadFacts.from_dict(wrapped.to_dict()).to_dict()
                disposition, reason = "typed_retained", ""
        except (ContractError, ValueError, TypeError, KeyError):
            pass
    context = {"version": 1, "profile": PROFILE, "doc_type": inputs["doc_type"],
               "parser_locale": locale, "parser_currency": currency,
               "instrument_source_contract": profile.instrument_source_contract,
               "page_count": inputs["page_count"], "validated_cell_count": inputs["validated_cell_count"],
               "lexical_scope": LEXICAL_SCOPE, "disposition": disposition, "reason": reason,
               "financial_admission": False}
    return dict(doc_id=receipt["doc_id"], facts_type=INTERPRETATION_KIND,
                facts=canonical(facts), context=canonical(context))
