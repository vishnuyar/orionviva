"""Retained raw readings and deterministic, immutable interpretations."""
from __future__ import annotations

from dataclasses import fields
from decimal import Decimal, InvalidOperation
import json
import hashlib
import importlib
from pathlib import Path
import sys

from vivacore.verify import normalize
from ..ingest import registry
from ..ingest.registry import profile_for
from ..ingest.statement import StatementFacts, TxnFact
from .schema import FORMAT, SCHEMA_VERSION
from .store import canonical, AuthorityError


_IMPLEMENTATION_MODULES = (
    "viva.sql_authority", "viva.sql_authority.store", "viva.sql_authority.schema",
    "viva.sql_authority.bank", "viva.sql_authority.reading", "viva.sql_authority.curated",
    "viva.sql_authority.identity", "viva.sql_authority.transfer_schema",
    "viva.sql_authority.transfers", "viva.sql_authority.transfer_verify",
    "viva.ledger.movement_identity", "viva.ingest.transfers",
    "viva.ledger.transfer_admission", "vivacore.versions", "viva.ledger.projection.movements", "viva.sample.resources", "viva.sample.curation",
    "viva.ledger.projection.accounts", "viva.acquisition",
    "viva.crypto", "viva.normalization_context", "viva.ingest.statement",
    "viva.ingest.registry", "viva.ingest.pipeline_models", "viva.ledger.identity",
    "viva.ledger.postings", "viva.ledger.events", "viva.ledger.streams",
    "vivacore.verify.arithmetic", "vivacore.verify.normalize",
)


def implementation_identity():
    """Hash a closed interpretation closure once per opened authority handle."""
    files = {}
    for name in _IMPLEMENTATION_MODULES:
        module = importlib.import_module(name)
        path = Path(module.__file__)
        if path.suffix != ".py" or not path.is_file():
            raise AuthorityError("deterministic interpretation source is missing")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    for name in ("sqlcipher3._sqlite3", "cryptography.hazmat.bindings._rust",
                 "cryptography.hazmat.primitives.ciphers.aead", "cryptography.hazmat.primitives.kdf.scrypt"):
        module = importlib.import_module(name)
        files[name] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    for package_name in ("pypdfium2", "pypdfium2_raw"):
        package = importlib.import_module(package_name)
        root = Path(package.__file__).parent
        sources = sorted(root.rglob("*.py"))
        if not sources or not (root / "__init__.py").is_file():
            raise AuthorityError("PDF interpretation wrapper is missing")
        for source in sources:
            files[package_name + "/" + source.relative_to(root).as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    for package_name in ("merchantcore",):
        package = importlib.import_module(package_name)
        root = Path(package.__file__).parent
        for source in sorted(root.rglob("*")):
            if source.is_file() and source.suffix in {".py", ".json", ".yaml", ".yml", ".txt", ".csv"}:
                files[package_name + "/" + source.relative_to(root).as_posix()] = hashlib.sha256(source.read_bytes()).hexdigest()
    from pypdfium2_raw import bindings
    native = Path(bindings._libs["pdfium"]._name)
    if not native.is_file():
        raise AuthorityError("loaded PDF interpretation binary is missing")
    files["pypdfium2_raw/loaded-native"] = hashlib.sha256(native.read_bytes()).hexdigest()
    python = {"implementation": sys.implementation.name,
              "cache_tag": sys.implementation.cache_tag,
              "version": list(sys.version_info), "build": sys.version}
    return {"files": files, "python": python,
            "sha256": hashlib.sha256(canonical([files, python]).encode()).hexdigest()}


def profile_descriptor(profile):
    if profile is None:
        return None
    return {"doc_type": profile.doc_type, "account_kind": profile.account_kind,
            "identity": profile.identity, "profile_version": profile.profile_version,
            "extract_base": profile.extract_base, "type_fragment": profile.type_fragment,
            "instrument_source_contract": profile.instrument_source_contract}


def current_read_context(implementation):
    """Capture trusted installed contracts before admitting a reader request."""
    return {"format": FORMAT, "schema_version": SCHEMA_VERSION,
            "implementation": implementation,
            "normalization_rules_version": normalize.RULES_VERSION,
            "profiles": {name: profile_descriptor(profile) for name, profile in sorted(registry._INDEX.items())}}


def capture_types(facts):
    """Retain runtime type facts which plain JSON would otherwise erase."""
    if type(facts) is not StatementFacts:
        return {"transactions": False, "decimals": False}
    transactions = (type(facts.transactions) is list
                    and all(type(line) is TxnFact for line in facts.transactions))
    decimals = (type(facts.opening_amount) is Decimal
                and type(facts.closing_amount) is Decimal and transactions
                and all(type(line.amount) is Decimal and
                        (line.running_balance is None or type(line.running_balance) is Decimal)
                        for line in facts.transactions))
    return {"transactions": transactions, "decimals": decimals}


def _facts_shape(value, tags):
    if (type(value) is not dict or set(value) != {field.name for field in fields(StatementFacts)}
            or type(tags) is not dict or set(tags) != {"transactions", "decimals", "read_context_id"}
            or tags["transactions"] is not True or tags["decimals"] is not True):
        return False
    for key in ("doc_id", "doc_type", "account_ref", "currency", "opening_amount",
                "opening_date", "closing_amount", "closing_date", "account_number",
                "institution", "source_account_ref"):
        if type(value[key]) is not str:
            return False
    for key in ("opening_page", "closing_page", "source_account_ref_page", "validated_source_page_count"):
        if value[key] is not None and type(value[key]) is not int:
            return False
    if type(value["account_names"]) is not list or any(type(name) is not str for name in value["account_names"]):
        return False
    if type(value["transactions"]) is not list:
        return False
    for line in value["transactions"]:
        if type(line) is not dict or set(line) != {field.name for field in fields(TxnFact)}:
            return False
        if any(type(line[key]) is not str for key in
               ("date", "description", "amount", "source_doc_id", "grade", "note", "source_reference", "counterparty_reference")):
            return False
        if line["page"] is not None and type(line["page"]) is not int:
            return False
        if line["running_balance"] is not None and type(line["running_balance"]) is not str:
            return False
    return True


def interpret(store, receipt):
    """Interpret only after the complete returned reading is durable."""
    existing = store._row("interpretations", "doc_id=?", (receipt["doc_id"],))
    reading = json.loads(receipt["body"])
    if receipt["facts_type"] == "curated":
        from .curated import authenticate
        try:
            authenticate(store, receipt, reading)
        except AuthorityError:
            return dict(doc_id=receipt["doc_id"], facts_type="source_rejected", facts="null", context="{}")
    if existing is not None:
        return existing
    raw_facts = json.loads(receipt["facts"])
    metadata_valid = all(type(reading[key]) is str for key in ("doc_type", "raw_text", "source_locale"))
    metadata_valid = metadata_valid and (reading["error"] is None or type(reading["error"]) is str)
    tags = json.loads(receipt["capture_types"])
    context_id = tags.get("read_context_id") if type(tags) is dict else None
    captured = (store._row("read_contexts", "context_id=?", (context_id,))
                if type(context_id) is str else None)
    read_context = json.loads(captured["body"]) if captured is not None else {}
    old_profile = (read_context.get("profiles", {}).get(reading["doc_type"].strip().lower())
                   if metadata_valid else None)
    profile = profile_for(reading["doc_type"]) if metadata_valid else None
    context = {"format": read_context.get("format"), "schema_version": read_context.get("schema_version"),
               "implementation": read_context.get("implementation"),
               "normalization_rules_version": read_context.get("normalization_rules_version"),
               "profile_version": old_profile.get("profile_version") if old_profile else None,
               "profile_identity": old_profile.get("identity") if old_profile else None,
               "profile_kind": old_profile.get("account_kind") if old_profile else None,
               "profile_descriptor": old_profile}
    contract_valid = (captured is not None
                      and hashlib.sha256(captured["body"].encode()).hexdigest() == context_id
                      and read_context.get("format") == FORMAT
                      and type(read_context.get("schema_version")) is int
                      and read_context["schema_version"] == SCHEMA_VERSION
                      and read_context.get("implementation") == store._implementation_identity
                      and read_context.get("normalization_rules_version") == normalize.RULES_VERSION
                      and (not metadata_valid or old_profile == profile_descriptor(profile)))
    facts_type = "invalid_reading" if not metadata_valid else receipt["facts_type"]
    facts_json = receipt["facts"]
    if metadata_valid and not contract_valid:
        facts_type = "contract_changed"
    if facts_type == "curated":
        from .curated import interpret_curated
        try:
            facts = interpret_curated(store, receipt, reading)
        except (AuthorityError, ValueError, KeyError, TypeError, IndexError, StopIteration):
            facts_type = "source_rejected"
        else:
            facts_type = "balance" if facts is not None else "unsupported"
            facts_json = canonical(facts.to_dict()) if facts is not None else "null"
    if facts_type == "balance" and receipt["facts_type"] != "curated":
        if not _facts_shape(raw_facts, tags):
            facts_type = "invalid_balance"
        else:
            try:
                facts = StatementFacts.from_dict(raw_facts)
            except (ValueError, InvalidOperation):
                facts_type = "invalid_balance"
            else:
                from .bank import valid_observations
                if valid_observations(facts):
                    facts_json = canonical(facts.to_dict())
                else:
                    facts_type = "invalid_balance"
    row = dict(doc_id=receipt["doc_id"], facts_type=facts_type,
               facts=facts_json, context=canonical(context))
    store._put("interpretations", row)
    return row
