import importlib.util
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "repair_loop.py"
SPEC = importlib.util.spec_from_file_location("repair_loop", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(MODULE)


def report(status="pass", decision="ready", complete=True, case_status="pass"):
    return {
        "product": "orionviva", "product_revision": "a" * 40,
        "status": status, "decision": decision, "complete": complete,
        "failures": [] if case_status != "fail" else [{"id": "oracle"}],
        "coverage": {
            "required_cases": 1, "executed_cases": 1,
            "missing_dimensions": [], "missing_capabilities": [], "missing_cases": [],
            "cases": [{"id": "first-open", "status": case_status}],
        },
    }


class ReportGateTests(unittest.TestCase):
    def test_accepts_only_complete_ready_pass(self):
        self.assertEqual(MODULE.classify_report(report(), "a" * 40)["classification"], "pass")

    def test_classifies_deterministic_failure(self):
        result = MODULE.classify_report(
            report(status="fail", decision="not_ready", complete=False, case_status="fail"), "a" * 40
        )
        self.assertEqual(result["classification"], "product_failure")
        self.assertEqual(result["failed_case_ids"], ["first-open"])

    def test_classifies_missing_verification_as_acceptance_gap(self):
        result = MODULE.classify_report(
            report(status="fail", decision="not_ready", complete=False, case_status="not_verified"), "a" * 40
        )
        self.assertEqual(result["classification"], "acceptance_gap")

    def test_product_failure_takes_priority_over_parallel_gap(self):
        value = report(status="fail", decision="not_ready", complete=False, case_status="fail")
        value["coverage"]["cases"].append({"id": "performance", "status": "not_verified"})
        value["coverage"]["required_cases"] = 2
        value["coverage"]["executed_cases"] = 2
        result = MODULE.classify_report(value, "a" * 40)
        self.assertEqual(result["classification"], "product_failure")
        self.assertEqual(result["gap_case_ids"], ["performance"])

    def test_rejects_stale_revision(self):
        result = MODULE.classify_report(report(), "b" * 40)
        self.assertEqual(result["classification"], "invalid_report")
        self.assertTrue(any("revision" in reason for reason in result["reasons"]))

    def test_rejects_case_omission(self):
        value = report()
        value["coverage"]["required_cases"] = 2
        self.assertEqual(MODULE.classify_report(value, "a" * 40)["classification"], "acceptance_gap")


if __name__ == "__main__":
    unittest.main()
