"""Synthetic ordinary CD capture codec contract; no storage operations."""
import copy
from decimal import Decimal
import json
import unittest

from vivacore.verify.normalize import RULES_VERSION
from viva.ingest import instrument_contracts as c
from viva.ingest.instrument_read import InstrumentReadFacts
from viva.ingest.pipeline_models import ModelPhase, ReadResult
from viva.normalization_context import ExtractionNormalizationContext
from viva.sql_authority.cd_receipts import ReceiptEncodingError, encode_ordinary_cd_receipt


DOC = "a" * 64
CONTEXT_ID = "b" * 64
LIMIT = 8 * 1024 * 1024
RESULT_KEYS = {"doc_type", "doc_type_confidence", "facts", "error", "raw_text", "model",
               "prompt_version", "input_mode", "cost_usd", "input_tokens", "output_tokens",
               "phases", "resolved_model", "usage_reported", "source_locale", "acquisition",
               "normalization_context"}
PHASE_KEYS = {"phase", "model", "prompt_version", "raw_text", "cost_usd", "input_tokens",
              "output_tokens", "input_mode", "parse_ok", "error", "resolved_model",
              "usage_reported", "transport_receipt_ids", "transport_complete", "extraction_id",
              "phase_attempt", "normalization_context"}
CASE_NAMES = (
    "test_minimal_cd_preserves_all_result_fields",
    "test_populated_cd_preserves_all_phase_fields",
    "test_instrument_wrapper_uses_instrument_facts",
    "test_null_wrapper_acquisition_is_omitted",
    "test_present_acquisitions_are_preserved",
    "test_top_context_uses_schema_one_wire",
    "test_phase_contexts_preserve_order_and_nulls",
    "test_null_top_context_has_explicit_none_tags",
    "test_capture_tags_have_exact_closed_schema",
    "test_body_and_facts_are_separate_canonical_strings",
    "test_raw_text_and_metadata_are_not_reinterpreted",
    "test_outputs_are_deterministic_and_detached",
    "test_read_result_dict_and_subclass_are_rejected",
    "test_instrument_facts_dict_and_subclass_are_rejected",
    "test_non_deposit_and_subclass_payloads_are_rejected",
    "test_phases_require_list_of_exact_model_phase",
    "test_context_dict_subclass_and_schema_two_are_rejected",
    "test_read_context_id_requires_exact_digest_shape",
    "test_wrong_metadata_scalar_types_are_rejected",
    "test_invalid_transport_metadata_is_rejected",
    "test_nonfinite_metadata_and_nested_json_are_rejected",
    "test_unsafe_json_keys_objects_cycles_and_unicode_are_rejected",
    "test_corrupted_typed_wrapper_is_revalidated",
    "test_receipt_utf8_byte_ceiling_is_enforced",
)


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False)


def _text(value):
    return c.SourcedText(value, c.Source(DOC, 1))


def _facts():
    identity = c.AccountIdentity(_text("Synthetic issuer"), _text("Synthetic CD"),
                                 _text("Synthetic holder"))
    payload = c.DepositFacts(identity, c.DepositSubtype.PERIODIC,
                            opening=c.Money(Decimal("0.0000"), "USD", c.Source(DOC, 1)))
    return InstrumentReadFacts(DOC, "term_deposit_statement", 0.5, payload, "USD")


def _result():
    return ReadResult("term_deposit_statement", 0.5, facts=_facts())


def _phase():
    return ModelPhase("synthetic-phase", "synthetic-model", "synthetic-prompt", "raw phase λ",
                      cost_usd=-0.25, input_tokens=-2, output_tokens=3, input_mode="opaque-mode",
                      parse_ok=False, error="synthetic error", resolved_model="resolved-synthetic",
                      usage_reported=True, transport_receipt_ids=["synthetic-link", ""],
                      transport_complete=False, extraction_id="synthetic-extraction", phase_attempt=-1)


def _context(locale=None, currency=None):
    return ExtractionNormalizationContext(1, RULES_VERSION, locale, currency)


def _encode(result):
    return encode_ordinary_cd_receipt(result, read_context_id=CONTEXT_ID)


class CDReceiptTests(unittest.TestCase):
    def test_minimal_cd_preserves_all_result_fields(self):
        body = json.loads(_encode(_result())["body"])
        self.assertEqual(set(body), RESULT_KEYS)
        self.assertEqual(body, {
            "doc_type": "term_deposit_statement", "doc_type_confidence": 0.5,
            "facts": InstrumentReadFacts.to_dict(_facts()), "error": None, "raw_text": "",
            "model": "", "prompt_version": "", "input_mode": "text+image", "cost_usd": 0.0,
            "input_tokens": 0, "output_tokens": 0, "phases": [], "resolved_model": "",
            "usage_reported": False, "source_locale": "", "acquisition": None,
            "normalization_context": None,
        })

    def test_populated_cd_preserves_all_phase_fields(self):
        result = _result()
        result.phases = [_phase()]
        phase = json.loads(_encode(result)["body"])["phases"][0]
        self.assertEqual(set(phase), PHASE_KEYS)
        self.assertEqual(phase, {
            "phase": "synthetic-phase", "model": "synthetic-model", "prompt_version": "synthetic-prompt",
            "raw_text": "raw phase λ", "cost_usd": -0.25, "input_tokens": -2, "output_tokens": 3,
            "input_mode": "opaque-mode", "parse_ok": False, "error": "synthetic error",
            "resolved_model": "resolved-synthetic", "usage_reported": True,
            "transport_receipt_ids": ["synthetic-link", ""], "transport_complete": False,
            "extraction_id": "synthetic-extraction", "phase_attempt": -1, "normalization_context": None,
        })

    def test_instrument_wrapper_uses_instrument_facts(self):
        result = _result()
        wire = json.loads(_encode(result)["facts"])
        self.assertIn("instrument_facts", wire)
        self.assertNotIn("payload", wire)
        self.assertEqual(wire["instrument_facts"]["opening"]["value"], "0.0000")
        self.assertEqual(wire, InstrumentReadFacts.to_dict(result.facts))

    def test_null_wrapper_acquisition_is_omitted(self):
        output = _encode(_result())
        self.assertNotIn("acquisition", json.loads(output["facts"]))
        self.assertIsNone(json.loads(output["body"])["acquisition"])

    def test_present_acquisitions_are_preserved(self):
        result = _result()
        acquisition = {
            "kind": "local-curation-v1", "sample_version": "five-year-life-v1",
            "corpus_manifest_sha256": "97a92df2512beb4938c498d7f1b43d20d4e3800cc38e9ce83012dda252f46800",
            "readings_sha256": "dbd302f394113ecb66c730a6d4bb40636897ba40cb9c3e4345084fb215fe1eab",
            "reading_contract": "curated-source-reading-v2", "document_sha256": DOC,
            "reading_sha256": "c" * 64,
        }
        result.facts = InstrumentReadFacts(DOC, "term_deposit_statement", None,
                                          result.facts.payload, "USD", acquisition)
        result.acquisition = {"opaque": [None, True, 2, 1.5, "λ", {"nested": "value"}]}
        body = json.loads(_encode(result)["body"])
        self.assertEqual(body["facts"]["acquisition"], acquisition)
        self.assertEqual(body["acquisition"], result.acquisition)
        self.assertEqual(body["doc_type_confidence"], 0.5)

    def test_top_context_uses_schema_one_wire(self):
        result = _result()
        result.normalization_context = _context("", "")
        body = json.loads(_encode(result)["body"])
        self.assertEqual(body["normalization_context"], {
            "schema_version": 1, "normalization_rules_version": RULES_VERSION,
            "parser_locale": "", "parser_currency": "",
        })
        self.assertNotIn("instrument_source_contract", body["normalization_context"])

    def test_phase_contexts_preserve_order_and_nulls(self):
        result = _result()
        first, middle, last = _phase(), _phase(), _phase()
        first.normalization_context = _context("en-AU", "AUD")
        last.normalization_context = _context()
        result.phases = [first, middle, last]
        output = _encode(result)
        contexts = [phase["normalization_context"] for phase in json.loads(output["body"])["phases"]]
        self.assertEqual(contexts, [
            {"schema_version": 1, "normalization_rules_version": RULES_VERSION,
             "parser_locale": "en-AU", "parser_currency": "AUD"}, None,
            {"schema_version": 1, "normalization_rules_version": RULES_VERSION,
             "parser_locale": None, "parser_currency": None},
        ])
        self.assertEqual(json.loads(output["capture_types"])["phase_context_runtime_types"],
                         ["ExtractionNormalizationContext", "none", "ExtractionNormalizationContext"])

    def test_null_top_context_has_explicit_none_tags(self):
        output = _encode(_result())
        tags = json.loads(output["capture_types"])
        self.assertIsNone(json.loads(output["body"])["normalization_context"])
        self.assertEqual(tags["normalization_context_runtime_type"], "none")
        self.assertEqual(tags["context_wire_profile"], "none")

    def test_capture_tags_have_exact_closed_schema(self):
        result = _result()
        result.normalization_context = _context()
        tags = json.loads(_encode(result)["capture_types"])
        self.assertEqual(tags, {
            "version": 1, "mode": "ordinary_cd_capture_v1",
            "facts_runtime_type": "InstrumentReadFacts", "payload_runtime_type": "DepositFacts",
            "facts_wire_profile": "instrument_wrapper_emitted_capture_v1",
            "normalization_context_runtime_type": "ExtractionNormalizationContext",
            "context_wire_profile": "extraction_context_capture_encode_v1",
            "phase_context_runtime_types": [], "read_context_id": CONTEXT_ID,
        })
        self.assertNotEqual(tags["mode"], "ordinary_cd_v1")
        self.assertNotEqual(tags["facts_wire_profile"], "instrument_wrapper_emitted_v1")
        self.assertNotEqual(tags["context_wire_profile"], "extraction_context_encode_v1")

    def test_body_and_facts_are_separate_canonical_strings(self):
        output = _encode(_result())
        self.assertEqual(set(output), {"body", "facts", "capture_types"})
        for name in ("body", "facts", "capture_types"):
            self.assertIs(type(output[name]), str)
            self.assertEqual(output[name], _canonical(json.loads(output[name])))
            output[name].encode("utf-8")
        self.assertEqual(output["facts"], _canonical(json.loads(output["body"])["facts"]))

    def test_raw_text_and_metadata_are_not_reinterpreted(self):
        result = _result()
        result.raw_text = '{not JSON}\nλ "quoted"'
        result.doc_type = "opaque-top-family"
        result.doc_type_confidence = -3
        result.model = "arbitrary-model"
        result.prompt_version = "arbitrary-prompt"
        result.input_mode = "arbitrary-mode"
        result.cost_usd = -2
        result.input_tokens = -1
        result.source_locale = "unlinked locale"
        result.phases = [_phase()]
        body_text = _encode(result)["body"]
        body = json.loads(body_text)
        for name in ("raw_text", "doc_type", "doc_type_confidence", "model", "prompt_version",
                     "input_mode", "cost_usd", "input_tokens", "source_locale"):
            self.assertEqual(body[name], getattr(result, name))
        self.assertEqual(body["phases"][0]["raw_text"], "raw phase λ")
        self.assertIn("λ", body_text)

    def test_outputs_are_deterministic_and_detached(self):
        result = _result()
        result.acquisition = {"nested": ["retained"]}
        result.phases = [_phase()]
        before = copy.deepcopy(result)
        output = _encode(result)
        self.assertEqual(_encode(result), output)
        self.assertEqual(result, before)
        saved = dict(output)
        result.acquisition["nested"].append("later")
        result.phases[0].transport_receipt_ids.append("later")
        result.raw_text = "later"
        self.assertEqual(output, saved)
        self.assertEqual(json.loads(output["body"])["acquisition"], {"nested": ["retained"]})

    def test_read_result_dict_and_subclass_are_rejected(self):
        class Derived(ReadResult):
            pass
        for value in ({"facts": _facts()}, Derived("term_deposit_statement", 0.5, facts=_facts())):
            with self.subTest(kind=type(value).__name__), self.assertRaises(ReceiptEncodingError):
                _encode(value)

    def test_instrument_facts_dict_and_subclass_are_rejected(self):
        class Derived(InstrumentReadFacts):
            pass
        facts = _facts()
        for value in (InstrumentReadFacts.to_dict(facts),
                      Derived(DOC, facts.doc_type, 0.5, facts.payload, "USD")):
            result = _result()
            result.facts = value
            with self.subTest(kind=type(value).__name__), self.assertRaises(ReceiptEncodingError):
                _encode(result)

    def test_non_deposit_and_subclass_payloads_are_rejected(self):
        class Derived(c.DepositFacts):
            pass
        facts = _facts()
        dated = c.SourcedDate("2026-01-01", c.Source(DOC, 1))
        mortgage = c.MortgageFacts(facts.payload.identity, dated, dated)
        for value in (mortgage, Derived(facts.payload.identity, c.DepositSubtype.PERIODIC)):
            result = _result()
            object.__setattr__(result.facts, "payload", value)
            with self.subTest(kind=type(value).__name__), self.assertRaises(ReceiptEncodingError):
                _encode(result)
        result = _result()
        result.facts = InstrumentReadFacts(DOC, "mortgage_statement", 0.5, mortgage, "USD")
        with self.assertRaises(ReceiptEncodingError):
            _encode(result)

    def test_phases_require_list_of_exact_model_phase(self):
        class Derived(ModelPhase):
            pass
        class DerivedList(list):
            pass
        for value in (None, (), {}, [_phase().__dict__],
                      [Derived("phase", "model", "prompt", "raw")], DerivedList([_phase()])):
            result = _result()
            result.phases = value
            with self.subTest(kind=type(value).__name__), self.assertRaises(ReceiptEncodingError):
                _encode(result)

    def test_context_dict_subclass_and_schema_two_are_rejected(self):
        class Derived(ExtractionNormalizationContext):
            pass
        values = ({"schema_version": 1}, Derived(1, RULES_VERSION, None, None),
                  ExtractionNormalizationContext(2, RULES_VERSION, None, None,
                                                 "mortgage-principal-source-v2"))
        for location in ("top", "phase"):
            for value in values:
                result = _result()
                if location == "top":
                    result.normalization_context = value
                else:
                    result.phases = [_phase()]
                    result.phases[0].normalization_context = value
                with self.subTest(location=location, kind=type(value).__name__), self.assertRaises(ReceiptEncodingError):
                    _encode(result)

    def test_read_context_id_requires_exact_digest_shape(self):
        class Derived(str):
            pass
        for value in (None, 1, b"b" * 64, "", "b" * 63, "b" * 65, "B" * 64,
                      "g" * 64, " " + "b" * 63, Derived(CONTEXT_ID)):
            with self.subTest(value_type=type(value).__name__), self.assertRaises(ReceiptEncodingError):
                encode_ordinary_cd_receipt(_result(), read_context_id=value)

    def test_wrong_metadata_scalar_types_are_rejected(self):
        # Explicit frozen populations cover every declared scalar shape.
        top_cases = (("doc_type", 1), ("doc_type_confidence", True), ("error", 3),
                     ("raw_text", None), ("model", []), ("prompt_version", False),
                     ("input_mode", 0), ("cost_usd", Decimal("1")), ("input_tokens", True),
                     ("output_tokens", 1.0), ("resolved_model", {}), ("usage_reported", 1),
                     ("source_locale", None), ("doc_type_confidence", None), ("cost_usd", "1"))
        phase_cases = (("phase", 1), ("model", None), ("prompt_version", False),
                       ("raw_text", []), ("cost_usd", True), ("input_tokens", False),
                       ("output_tokens", 1.0), ("input_mode", {}), ("parse_ok", 1),
                       ("error", []), ("resolved_model", 0), ("usage_reported", 0),
                       ("extraction_id", None), ("phase_attempt", True))
        for name, value in top_cases:
            result = _result()
            setattr(result, name, value)
            with self.subTest(location="top", name=name), self.assertRaises(ReceiptEncodingError):
                _encode(result)
        for name, value in phase_cases:
            result = _result()
            result.phases = [_phase()]
            setattr(result.phases[0], name, value)
            with self.subTest(location="phase", name=name), self.assertRaises(ReceiptEncodingError):
                _encode(result)

    def test_invalid_transport_metadata_is_rejected(self):
        for name, value in (("transport_receipt_ids", ("id",)), ("transport_receipt_ids", "id"),
                            ("transport_receipt_ids", [1]), ("transport_receipt_ids", [None]),
                            ("transport_complete", 1), ("transport_complete", "true"),
                            ("phase_attempt", 1.5)):
            result = _result()
            result.phases = [_phase()]
            setattr(result.phases[0], name, value)
            with self.subTest(name=name, kind=type(value).__name__), self.assertRaises(ReceiptEncodingError):
                _encode(result)

    def test_nonfinite_metadata_and_nested_json_are_rejected(self):
        for number in (float("nan"), float("inf"), -float("inf")):
            for location, name in (("top", "cost_usd"), ("top", "doc_type_confidence"),
                                   ("phase", "cost_usd"), ("acquisition", "nested")):
                result = _result()
                if location == "top":
                    setattr(result, name, number)
                elif location == "phase":
                    result.phases = [_phase()]
                    setattr(result.phases[0], name, number)
                else:
                    result.acquisition = {name: [number]}
                with self.subTest(location=location, name=name, number=repr(number)), self.assertRaises(ReceiptEncodingError):
                    _encode(result)

    def test_unsafe_json_keys_objects_cycles_and_unicode_are_rejected(self):
        cycle_list = []
        cycle_list.append(cycle_list)
        cycle_dict = {}
        cycle_dict["self"] = cycle_dict
        unsafe = ({1: "nonstring-key"}, {"object": object()}, {"decimal": Decimal("1")},
                  {"tuple": (1,)}, {"cycle": cycle_list}, cycle_dict,
                  {"surrogate": "\ud800"}, {"\udfff": "invalid-key"}, [], "not-a-dict")
        for index, value in enumerate(unsafe):
            result = _result()
            result.acquisition = value
            with self.subTest(index=index), self.assertRaises(ReceiptEncodingError):
                _encode(result)
        for location in ("raw_text", "phase_raw_text", "facts_text"):
            result = _result()
            if location == "raw_text":
                result.raw_text = "\ud800"
            elif location == "phase_raw_text":
                result.phases = [_phase()]
                result.phases[0].raw_text = "\ud800"
            else:
                object.__setattr__(result.facts.payload.identity.holder, "value", "\ud800")
            with self.subTest(location=location), self.assertRaises(ReceiptEncodingError):
                _encode(result)

    def test_corrupted_typed_wrapper_is_revalidated(self):
        for corruption in ("confidence", "currency", "source", "decimal", "subtype", "helper_override"):
            result = _result()
            if corruption == "confidence":
                object.__setattr__(result.facts, "doc_type_confidence", float("nan"))
            elif corruption == "currency":
                object.__setattr__(result.facts, "currency", "AUD")
            elif corruption == "source":
                object.__setattr__(result.facts.payload.identity.holder.source, "page", True)
            elif corruption == "decimal":
                object.__setattr__(result.facts.payload.opening, "value", Decimal("NaN"))
            elif corruption == "subtype":
                object.__setattr__(result.facts.payload, "subtype", "periodic")
            else:
                object.__setattr__(result.facts, "doc_type_confidence", float("nan"))
                object.__setattr__(result.facts, "__post_init__", lambda: None)
                object.__setattr__(result.facts, "to_dict", lambda: InstrumentReadFacts.to_dict(_facts()))
            with self.subTest(corruption=corruption), self.assertRaises(ReceiptEncodingError):
                _encode(result)

    def test_receipt_utf8_byte_ceiling_is_enforced(self):
        result = _result()
        overhead = len(_encode(result)["body"].encode("utf-8"))
        padding = LIMIT - overhead
        self.assertGreater(padding, 0)
        result.raw_text = "x" * padding
        self.assertEqual(len(_encode(result)["body"].encode("utf-8")), LIMIT)
        result.raw_text += "x"
        with self.assertRaises(ReceiptEncodingError):
            _encode(result)
        result.raw_text = "é" * (padding // 2) + "x" * (padding % 2)
        self.assertEqual(len(_encode(result)["body"].encode("utf-8")), LIMIT)
        result.raw_text += "é"
        with self.assertRaises(ReceiptEncodingError):
            _encode(result)


def suite():
    return unittest.TestSuite(CDReceiptTests(name) for name in CASE_NAMES)
