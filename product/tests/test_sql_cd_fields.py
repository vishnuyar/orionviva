"""Lossless structural associations for synthetic retained CD wire values."""
import copy
import json
import unittest

from viva.sql_authority.cd_fields import enumerate_wire_associations


DOC = "a" * 64
FACTS = "synthetic-facts-context"
CASE_NAMES = (
    "test_minimal_paths_order", "test_terms_paths_order", "test_movement_ordinals",
    "test_null_movements", "test_empty_movements", "test_null_terms",
    "test_omitted_acquisition", "test_null_acquisition", "test_local_acquisition",
    "test_decimal_spelling", "test_unknown_unsourced", "test_unknown_sourced",
    "test_known_unsourced", "test_own_bindings", "test_companion_self_bindings",
    "test_no_borrowed_anchor", "test_wrong_family", "test_missing_extra_fields",
    "test_duplicate_keys", "test_foreign_document", "test_invalid_pages",
    "test_nonfinite_values", "test_movement_cap", "test_detached_outputs",
)
MINIMAL_PATHS = [
    ["doc_id"], ["doc_type"], ["doc_type_confidence"], ["currency"], ["acquisition"],
    ["instrument_facts"], ["instrument_facts", "identity"],
    ["instrument_facts", "identity", "institution"],
    ["instrument_facts", "identity", "account_reference"],
    ["instrument_facts", "identity", "holder"],
    ["instrument_facts", "subtype"], ["instrument_facts", "start"],
    ["instrument_facts", "end"], ["instrument_facts", "opening"],
    ["instrument_facts", "closing"], ["instrument_facts", "movements"],
    ["instrument_facts", "terms"], ["instrument_facts", "uncredited_interest"],
]
TERMS_PATHS = [
    ["doc_id"], ["doc_type"], ["doc_type_confidence"], ["currency"], ["acquisition"],
    ["instrument_facts"], ["instrument_facts", "identity"],
    ["instrument_facts", "identity", "institution"],
    ["instrument_facts", "identity", "account_reference"],
    ["instrument_facts", "identity", "holder"],
    ["instrument_facts", "subtype"], ["instrument_facts", "start"],
    ["instrument_facts", "end"], ["instrument_facts", "opening"],
    ["instrument_facts", "closing"], ["instrument_facts", "movements"],
    ["instrument_facts", "terms"], ["instrument_facts", "terms", "principal"],
    ["instrument_facts", "terms", "opened"], ["instrument_facts", "terms", "maturity"],
    ["instrument_facts", "terms", "rate"], ["instrument_facts", "terms", "rate_basis"],
    ["instrument_facts", "terms", "day_count"],
    ["instrument_facts", "terms", "compounding"],
    ["instrument_facts", "terms", "withdrawal_restriction"],
    ["instrument_facts", "terms", "rate_basis_source"],
    ["instrument_facts", "terms", "day_count_source"],
    ["instrument_facts", "uncredited_interest"],
]


def _source(page=1):
    return {"doc_id": DOC, "page": page}


def _text(value, page=1):
    return {"value": value, "source": _source(page)}


def _money(value="1000.00", page=1):
    return {"value": value, "currency": "USD", "source": _source(page)}


def _wire():
    return {
        "doc_id": DOC, "doc_type": "term_deposit_statement",
        "doc_type_confidence": 0.75, "currency": "USD",
        "instrument_facts": {
            "identity": {"institution": _text("Synthetic issuer"),
                         "account_reference": _text("CD-SYNTHETIC"),
                         "holder": _text("Synthetic holder")},
            "subtype": "periodic", "start": None, "end": None,
            "opening": None, "closing": None, "movements": None,
            "terms": None, "uncredited_interest": None,
        },
    }


def _terms():
    return {
        "principal": _money(), "opened": _text("2026-01-01"),
        "maturity": _text("2026-12-31", 2),
        "rate": {"percent": "3.2500", "source": _source(2)},
        "rate_basis": "unknown", "day_count": "unknown",
        "compounding": None,
        "withdrawal_restriction": _text("Complete synthetic withdrawal terms; no inferred release.", 2),
        "rate_basis_source": None, "day_count_source": None,
    }


def _movement(reference="SYNTHETIC-ROW", page=1):
    return {"kind": "interest_credit", "amount": _money("1.00", page),
            "dated": _text("2026-01-31", page), "reference": _text(reference, page),
            "counterparty_reference": None}


def _enumerate(value, **context):
    return enumerate_wire_associations(json.dumps(value), facts_id=FACTS,
                                       document_id=DOC, page_count=2, **context)


def _indexed(rows):
    return {tuple(row["field_path"]): row for row in rows}


class CDFieldsTests(unittest.TestCase):
    def test_minimal_paths_order(self):
        rows = _enumerate(_wire())
        self.assertEqual([row["field_path"] for row in rows], MINIMAL_PATHS)
        self.assertEqual(len(rows), 18)
        for row in rows:
            self.assertEqual(set(row), {"version", "facts_id", "field_path", "field_type",
                                       "state", "wire_value", "source_binding", "lexical_binding"})
            self.assertEqual(row["version"], 1)
            self.assertEqual(row["facts_id"], FACTS)
            self.assertIsNone(row["lexical_binding"])
        self.assertEqual([row["field_type"] for row in rows],
                         ["metadata", "metadata", "metadata", "metadata", "metadata",
                          "object", "object", "text", "text", "text", "enum", "date",
                          "date", "money", "money", "population", "object", "money"])

    def test_terms_paths_order(self):
        wire = _wire()
        wire["instrument_facts"]["terms"] = _terms()
        rows = _enumerate(wire)
        self.assertEqual([row["field_path"] for row in rows], TERMS_PATHS)
        self.assertEqual(len(rows), 28)
        row = _indexed(rows)[("instrument_facts", "terms", "withdrawal_restriction")]
        self.assertEqual(row["wire_value"]["value"],
                         "Complete synthetic withdrawal terms; no inferred release.")

    def test_movement_ordinals(self):
        wire = _wire()
        wire["instrument_facts"]["movements"] = [_movement("SYNTHETIC-FIRST"),
                                                  _movement("SYNTHETIC-SECOND", 2)]
        rows = _enumerate(wire)
        actual = [row["field_path"] for row in rows if len(row["field_path"]) >= 3
                  and row["field_path"][:2] == ["instrument_facts", "movements"]]
        self.assertEqual(actual, [
            ["instrument_facts", "movements", 0], ["instrument_facts", "movements", 0, "kind"],
            ["instrument_facts", "movements", 0, "amount"], ["instrument_facts", "movements", 0, "dated"],
            ["instrument_facts", "movements", 0, "reference"],
            ["instrument_facts", "movements", 0, "counterparty_reference"],
            ["instrument_facts", "movements", 1], ["instrument_facts", "movements", 1, "kind"],
            ["instrument_facts", "movements", 1, "amount"], ["instrument_facts", "movements", 1, "dated"],
            ["instrument_facts", "movements", 1, "reference"],
            ["instrument_facts", "movements", 1, "counterparty_reference"],
        ])
        self.assertEqual(len(rows), 30)
        self.assertEqual(_indexed(rows)[("instrument_facts", "movements", 1, "reference")]
                         ["wire_value"]["value"], "SYNTHETIC-SECOND")

    def test_null_movements(self):
        rows = _enumerate(_wire())
        selected = [row for row in rows if row["field_path"][:2] == ["instrument_facts", "movements"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["state"], "null")
        self.assertIsNone(selected[0]["wire_value"])

    def test_empty_movements(self):
        wire = _wire()
        wire["instrument_facts"]["movements"] = []
        rows = _enumerate(wire)
        selected = [row for row in rows if row["field_path"][:2] == ["instrument_facts", "movements"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["state"], "present")
        self.assertEqual(selected[0]["wire_value"], [])

    def test_null_terms(self):
        rows = _enumerate(_wire())
        selected = [row for row in rows if row["field_path"][:2] == ["instrument_facts", "terms"]]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]["state"], "null")
        self.assertIsNone(selected[0]["source_binding"])

    def test_omitted_acquisition(self):
        row = _indexed(_enumerate(_wire()))[("acquisition",)]
        self.assertEqual(row["state"], "omitted")
        self.assertIsNone(row["wire_value"])
        self.assertIsNone(row["source_binding"])
        self.assertIsNone(row["lexical_binding"])

    def test_null_acquisition(self):
        wire = _wire()
        wire["acquisition"] = None
        row = _indexed(_enumerate(wire))[("acquisition",)]
        self.assertEqual(row["state"], "null")
        self.assertIsNone(row["wire_value"])
        self.assertIsNone(row["source_binding"])

    def test_local_acquisition(self):
        wire = _wire()
        wire["doc_type_confidence"] = None
        wire["acquisition"] = {
            "kind": "local-curation-v1", "sample_version": "five-year-life-v1",
            "corpus_manifest_sha256": "97a92df2512beb4938c498d7f1b43d20d4e3800cc38e9ce83012dda252f46800",
            "readings_sha256": "dbd302f394113ecb66c730a6d4bb40636897ba40cb9c3e4345084fb215fe1eab",
            "reading_contract": "curated-source-reading-v2", "document_sha256": DOC,
            "reading_sha256": "b" * 64,
        }
        rows = _indexed(_enumerate(wire))
        self.assertEqual(rows[("acquisition",)]["state"], "present")
        self.assertEqual(rows[("acquisition",)]["wire_value"], wire["acquisition"])
        self.assertIsNone(rows[("acquisition",)]["source_binding"])
        self.assertEqual(rows[("doc_type_confidence",)]["state"], "null")
        wire["doc_type_confidence"] = 0.75
        with self.assertRaises(ValueError):
            _enumerate(wire)

    def test_decimal_spelling(self):
        wire = _wire()
        wire["instrument_facts"]["opening"] = _money("0.0000")
        wire["instrument_facts"]["closing"] = _money("1.2300E+3")
        wire["instrument_facts"]["terms"] = _terms()
        rows = _indexed(_enumerate(wire))
        self.assertEqual(rows[("instrument_facts", "opening")]["state"], "present")
        self.assertEqual(rows[("instrument_facts", "opening")]["wire_value"]["value"], "0.0000")
        self.assertEqual(rows[("instrument_facts", "closing")]["wire_value"]["value"], "1.2300E+3")
        self.assertEqual(rows[("instrument_facts", "terms", "rate")]["wire_value"]["percent"], "3.2500")

    def test_unknown_unsourced(self):
        wire = _wire()
        wire["instrument_facts"]["terms"] = _terms()
        rows = _indexed(_enumerate(wire))
        for field in ("rate_basis", "day_count"):
            self.assertEqual(rows[("instrument_facts", "terms", field)]["wire_value"], "unknown")
            self.assertIsNone(rows[("instrument_facts", "terms", field)]["source_binding"])

    def test_unknown_sourced(self):
        wire = _wire()
        wire["instrument_facts"]["terms"] = _terms()
        wire["instrument_facts"]["terms"]["rate_basis_source"] = _source(2)
        row = _indexed(_enumerate(wire))[("instrument_facts", "terms", "rate_basis")]
        self.assertEqual(row["wire_value"], "unknown")
        self.assertEqual(row["source_binding"], {"mode": "companion",
                         "source_path": ["instrument_facts", "terms", "rate_basis_source"],
                         "document_id": DOC, "page": 2})

    def test_known_unsourced(self):
        wire = _wire()
        wire["instrument_facts"]["terms"] = _terms()
        wire["instrument_facts"]["terms"]["rate_basis"] = "simple_nominal"
        wire["instrument_facts"]["terms"]["day_count"] = "actual_365"
        rows = _indexed(_enumerate(wire))
        self.assertEqual(rows[("instrument_facts", "terms", "rate_basis")]["wire_value"], "simple_nominal")
        self.assertEqual(rows[("instrument_facts", "terms", "day_count")]["wire_value"], "actual_365")
        self.assertIsNone(rows[("instrument_facts", "terms", "rate_basis")]["source_binding"])
        self.assertIsNone(rows[("instrument_facts", "terms", "day_count")]["source_binding"])

    def test_own_bindings(self):
        wire = _wire()
        wire["instrument_facts"]["opening"] = _money("0", 2)
        wire["instrument_facts"]["movements"] = [_movement(page=2)]
        rows = _indexed(_enumerate(wire))
        for path, page in [(["instrument_facts", "identity", "holder"], 1),
                           (["instrument_facts", "opening"], 2),
                           (["instrument_facts", "movements", 0, "amount"], 2),
                           (["instrument_facts", "movements", 0, "dated"], 2)]:
            self.assertEqual(rows[tuple(path)]["source_binding"],
                             {"mode": "own", "source_path": path + ["source"],
                              "document_id": DOC, "page": page})

    def test_companion_self_bindings(self):
        wire = _wire()
        wire["instrument_facts"]["terms"] = _terms()
        wire["instrument_facts"]["terms"]["rate_basis_source"] = _source(1)
        wire["instrument_facts"]["terms"]["day_count_source"] = _source(2)
        rows = _indexed(_enumerate(wire))
        for field, page in [("rate_basis", 1), ("day_count", 2)]:
            source_path = ["instrument_facts", "terms", field + "_source"]
            self.assertEqual(rows[("instrument_facts", "terms", field)]["source_binding"],
                             {"mode": "companion", "source_path": source_path,
                              "document_id": DOC, "page": page})
            self.assertEqual(rows[tuple(source_path)]["field_type"], "source")
            self.assertEqual(rows[tuple(source_path)]["source_binding"],
                             {"mode": "self", "source_path": source_path,
                              "document_id": DOC, "page": page})

    def test_no_borrowed_anchor(self):
        wire = _wire()
        wire["instrument_facts"]["terms"] = _terms()
        wire["instrument_facts"]["movements"] = [_movement()]
        rows = _indexed(_enumerate(wire))
        for path in [("doc_id",), ("currency",), ("instrument_facts",),
                     ("instrument_facts", "identity"), ("instrument_facts", "subtype"),
                     ("instrument_facts", "movements"), ("instrument_facts", "movements", 0),
                     ("instrument_facts", "movements", 0, "kind"), ("instrument_facts", "terms")]:
            self.assertIsNone(rows[path]["source_binding"], path)
        self.assertTrue(all(row["lexical_binding"] is None for row in rows.values()))

    def test_wrong_family(self):
        for family in ("mortgage_statement", "refinance_settlement", "property_tax_receipt", "unsupported"):
            with self.subTest(family=family):
                wire = _wire()
                wire["doc_type"] = family
                with self.assertRaises(ValueError):
                    _enumerate(wire)

    def test_missing_extra_fields(self):
        invalid = []
        wire = _wire()
        del wire["instrument_facts"]["start"]
        invalid.append(("missing_optional_wire_field", wire))
        wire = _wire()
        wire["instrument_facts"]["extra"] = None
        invalid.append(("extra_payload_field", wire))
        wire = _wire()
        wire["extra"] = None
        invalid.append(("extra_wrapper_field", wire))
        wire = _wire()
        wire["instrument_facts"]["identity"]["holder"]["extra"] = None
        invalid.append(("extra_typed_scalar_field", wire))
        wire = _wire()
        wire["doc_type_confidence"] = None
        invalid.append(("unavailable_confidence_without_acquisition", wire))
        wire = _wire()
        wire["instrument_facts"]["opening"] = _money()
        wire["instrument_facts"]["opening"]["currency"] = "EUR"
        invalid.append(("currency_mismatch", wire))
        for label, value in invalid + [("list_root", []), ("null_root", None), ("scalar_root", 1)]:
            with self.subTest(defect=label), self.assertRaises(ValueError):
                _enumerate(value)
        for name, value in [("facts_id", ""), ("facts_id", True),
                            ("document_id", " "), ("document_id", 1)]:
            context = {"facts_id": FACTS, "document_id": DOC, "page_count": 2}
            context[name] = value
            with self.subTest(context=name, value=value), self.assertRaises(ValueError):
                enumerate_wire_associations(json.dumps(_wire()), **context)
        for value in ({}, None, 42):
            with self.subTest(nontext=type(value).__name__), self.assertRaises(ValueError):
                enumerate_wire_associations(value, facts_id=FACTS, document_id=DOC, page_count=2)

    def test_duplicate_keys(self):
        text = json.dumps(_wire())
        duplicate_top = '{"doc_id":"other",' + text[1:]
        duplicate_nested = text.replace('"subtype": "periodic"',
                                        '"subtype": "opening", "subtype": "periodic"')
        for label, value in [("top", duplicate_top), ("nested", duplicate_nested),
                             ("invalid_json", "{"), ("extra_json", text + " {}")]:
            with self.subTest(defect=label), self.assertRaises(ValueError):
                enumerate_wire_associations(value, facts_id=FACTS, document_id=DOC, page_count=2)

    def test_foreign_document(self):
        wire = _wire()
        wire["instrument_facts"]["identity"]["holder"]["source"]["doc_id"] = "b" * 64
        with self.assertRaises(ValueError):
            _enumerate(wire)
        wire = _wire()
        with self.assertRaises(ValueError):
            enumerate_wire_associations(json.dumps(wire), facts_id=FACTS,
                                        document_id="b" * 64, page_count=2)

    def test_invalid_pages(self):
        for page in (True, False, 0, -1, 3, 1.0, "1"):
            wire = _wire()
            wire["instrument_facts"]["identity"]["holder"]["source"]["page"] = page
            with self.subTest(source_page=page), self.assertRaises(ValueError):
                _enumerate(wire)
        for count in (True, False, 0, -1, None, 1.0, "2"):
            with self.subTest(page_count=count), self.assertRaises(ValueError):
                enumerate_wire_associations(json.dumps(_wire()), facts_id=FACTS,
                                            document_id=DOC, page_count=count)

    def test_nonfinite_values(self):
        for value in ("NaN", "Infinity", "-Infinity", "bad-decimal"):
            wire = _wire()
            wire["instrument_facts"]["opening"] = _money(value)
            with self.subTest(decimal=value), self.assertRaises(ValueError):
                _enumerate(wire)
        text = json.dumps(_wire())
        for value in ("NaN", "Infinity", "-Infinity", "1e999"):
            invalid = text.replace('"doc_type_confidence": 0.75', '"doc_type_confidence": ' + value)
            with self.subTest(json_number=value), self.assertRaises(ValueError):
                enumerate_wire_associations(invalid, facts_id=FACTS, document_id=DOC, page_count=2)
        oversized = json.dumps(_wire()) + " " * (8 * 1024 * 1024)
        with self.assertRaises(ValueError):
            enumerate_wire_associations(oversized, facts_id=FACTS, document_id=DOC, page_count=2)

    def test_movement_cap(self):
        wire = _wire()
        wire["instrument_facts"]["movements"] = [_movement() for _ in range(1000)]
        rows = _enumerate(wire)
        self.assertEqual(len(rows), 6018)
        self.assertIn(["instrument_facts", "movements", 999, "counterparty_reference"],
                      [row["field_path"] for row in rows])
        wire["instrument_facts"]["movements"].append(_movement())
        with self.assertRaises(ValueError):
            _enumerate(wire)

    def test_detached_outputs(self):
        wire = _wire()
        wire["instrument_facts"]["terms"] = _terms()
        wire["instrument_facts"]["opening"] = _money("0.0000")
        text = json.dumps(wire, indent=2)
        saved = copy.deepcopy(wire)
        rows = enumerate_wire_associations(text, facts_id=FACTS, document_id=DOC, page_count=2)
        selected = _indexed(rows)
        selected[("instrument_facts",)]["wire_value"]["opening"]["value"] = "changed"
        self.assertEqual(selected[("instrument_facts", "opening")]["wire_value"]["value"], "0.0000")
        selected[("instrument_facts", "opening")]["wire_value"]["source"]["page"] = 999
        self.assertEqual(selected[("instrument_facts", "opening")]["source_binding"]["page"], 1)
        selected[("instrument_facts", "terms")]["wire_value"]["principal"]["source"]["page"] = 999
        self.assertEqual(selected[("instrument_facts", "terms", "principal")]["wire_value"]["source"]["page"], 1)
        selected[("instrument_facts", "terms", "principal")]["field_path"].append("changed")
        self.assertEqual(selected[("instrument_facts", "terms", "opened")]["field_path"],
                         ["instrument_facts", "terms", "opened"])
        self.assertEqual(wire, saved)
        self.assertEqual(text, json.dumps(saved, indent=2))


def suite():
    return unittest.TestSuite(CDFieldsTests(name) for name in CASE_NAMES)
