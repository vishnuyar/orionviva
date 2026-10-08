"""Counterexamples for the public acceptance inventory guard."""
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest

SPEC=importlib.util.spec_from_file_location("catalog_guard",Path(__file__).with_name("check_catalog.py"))
guard=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(guard)


class CatalogGuardTest(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.acceptance=Path(self.temporary.name)/"acceptance"
        shutil.copytree(Path(__file__).parent,self.acceptance,ignore=shutil.ignore_patterns("__pycache__"),copy_function=shutil.copyfile)

    def test_current_catalog_has65_unique_cases_and17_families(self):
        result=guard.check_catalog(self.acceptance)
        self.assertEqual(result["human_cases"],65)
        self.assertEqual(result["new_family_cases"],17)

    def test_missing_supported_family_is_rejected(self):
        path=self.acceptance/"scenarios/financial-capabilities.md"
        path.write_text(path.read_text().replace('**Family:** `cash_flow_scenario`.','**Family:** `other`.'))
        with self.assertRaisesRegex(ValueError,"supported family"):
            guard.check_catalog(self.acceptance)

    def test_duplicate_or_removed_original_case_is_rejected(self):
        path=self.acceptance/"scenarios/guidance.md"
        path.write_text(path.read_text().replace("## GUIDE-006","## GUIDE-005"))
        with self.assertRaisesRegex(ValueError,"baseline"):
            guard.check_catalog(self.acceptance)

    def test_false_automated_feature_coverage_is_rejected(self):
        # A synthetic declaration packet isolates the guard from any evaluator
        # run or provider. The mutation changes evidence status, not arithmetic.
        pack=Path(self.temporary.name)/"pack";scenarios=pack/"scenarios";scenarios.mkdir(parents=True)
        workflows=pack/"workflows";workflows.mkdir()
        identities=["financial-"+family.replace("_","-") for family in guard.FAMILIES]
        (pack/"product.json").write_text(json.dumps({"evaluation":{"required_capabilities":identities}}))
        rows=[{"id":ident,"status":"not_verified","mapped":False,"executed":False} for ident in identities]
        coverage=pack/"financial-capability-coverage.json";coverage.write_text(json.dumps({"cases":rows}))
        for ident in identities:
            (scenarios/(ident+".json")).write_text(json.dumps({"id":ident,"covers":[ident],"required":True,"verification":"deterministic"}))
        for i in range(6):(scenarios/f"old-{i}.json").write_text('{}')
        for i in range(5):(workflows/f"old-{i}.json").write_text('{}')
        self.assertEqual(guard.check_catalog(self.acceptance,sibling_pack=pack)["external_new_unverified"],17)
        rows[0]["status"]="pass";coverage.write_text(json.dumps({"cases":rows}))
        with self.assertRaisesRegex(ValueError,"falsely claims"):
            guard.check_catalog(self.acceptance,sibling_pack=pack)


if __name__=="__main__":unittest.main()
