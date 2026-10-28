"""Closed backend-owned inputs to one ordinary extraction interpretation."""
from __future__ import annotations
from dataclasses import dataclass,asdict
import json
from vivacore.verify.normalize import RULES_VERSION

MORTGAGE_SOURCE_CONTRACT = 'mortgage-principal-source-v2'
MORTGAGE_PROMPT_PARTS = frozenset({
    ('mortgage-base-v2', 'mortgage-v2'),
    ('mortgage-base-v2', 'mortgage-v3'),
})
MORTGAGE_PROMPT_SUPPORT = frozenset({'untrusted-frame-v1', 'retry-syntax-v1', 'retry-value-v2'})


@dataclass(frozen=True)
class ExtractionNormalizationContext:
    schema_version: int
    normalization_rules_version: str
    parser_locale: str | None
    parser_currency: str | None
    instrument_source_contract: str | None = None

    def __post_init__(self):
        if type(self.schema_version) is not int or self.schema_version not in (1, 2):
            raise ValueError('unsupported extraction context schema')
        if ((self.schema_version == 1 and self.instrument_source_contract is not None) or
                (self.schema_version == 2 and self.instrument_source_contract != MORTGAGE_SOURCE_CONTRACT)):
            raise ValueError('unsupported instrument source contract')
        if (type(self.normalization_rules_version) is not str or
                len(self.normalization_rules_version.encode('utf-8')) > 32 or
                self.normalization_rules_version != RULES_VERSION):
            raise ValueError('unsupported normalization rules implementation')
        for value,limit in [(self.parser_locale,64),(self.parser_currency,16)]:
            if value is not None and (type(value) is not str or len(value.encode('utf-8')) > limit):
                raise ValueError('invalid extraction parser input context')
        if len(json.dumps(asdict(self),separators=(',',':'),ensure_ascii=False).encode('utf-8')) > 512:
            raise ValueError('extraction context descriptor exceeds bound')


def encode_context(value):
    if type(value) is not ExtractionNormalizationContext:
        raise ValueError('typed backend extraction context required')
    value.__post_init__()
    encoded = asdict(value)
    if value.schema_version == 1:
        encoded.pop('instrument_source_contract')
    return encoded


def decode_context(value):
    fields = {'schema_version','normalization_rules_version','parser_locale','parser_currency'}
    if type(value) is not dict or set(value) != (fields | {'instrument_source_contract'}
            if value.get('schema_version') == 2 else fields):
        raise ValueError('invalid recorded extraction context')
    return ExtractionNormalizationContext(**value)


def source_contract_for_claim(context, doc_type, prompt_version):
    """Bind the retained backend selector to its immutable prompt family."""
    if context is not None:
        encode_context(context)
    parts = (prompt_version[len('extract:'):].split('+')
             if isinstance(prompt_version, str) and prompt_version.startswith('extract:') else [])
    selected = context.instrument_source_contract if context is not None else None
    if selected is not None:
        if (doc_type != 'mortgage_statement' or tuple(parts[:2]) not in MORTGAGE_PROMPT_PARTS
                or any(part not in MORTGAGE_PROMPT_SUPPORT for part in parts[2:])
                or len(parts[2:]) != len(set(parts[2:]))):
            raise ValueError('mortgage source context and prompt do not match')
    elif any(part in pair for pair in MORTGAGE_PROMPT_PARTS for part in parts):
        raise ValueError('mortgage source prompt requires its backend context')
    return selected
