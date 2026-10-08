"""Check additive human coverage and truthful automated feature declarations.

This reads public test definitions only. It never opens a vault or executes a
product, model or provider. Declared coverage cannot stand in for observed runs.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

FAMILIES = (
    "spending_by_category", "spending_by_merchant", "spending_by_account",
    "spending_comparison", "movement_search", "period_income", "period_surplus",
    "recurring_spending", "recorded_cash", "account_value_history",
    "statement_period_coverage", "known_remainder", "upcoming_obligations",
    "goal_progress", "savings_scenario", "loan_payoff_scenario", "cash_flow_scenario",
)
BASELINE_COUNTS = {"VAULT":8,"IMPORT":7,"PICTURE":8,"TRUST":7,"GUIDE":6,"ACCESS":4,"RESILIENCE":5}


def check_catalog(acceptance: Path, *, sibling_pack: Path | None = None) -> dict:
    headings = []
    for path in sorted((acceptance / "scenarios").glob("*.md")):
        if path.name != "retired.md":
            headings.extend(re.findall(r"^## ([A-Z]+-\d{3})\b", path.read_text(), re.MULTILINE))
    expected = {f"{family}-{i:03}" for family, count in BASELINE_COUNTS.items() for i in range(1,count+1)}
    expected |= {f"GUIDE-{i:03}" for i in range(7,27)}
    if len(headings) != 65 or set(headings) != expected:
        raise ValueError("human catalog must retain45 baseline and20 additive unique cases")
    text = (acceptance / "scenarios/financial-capabilities.md").read_text()
    family_labels = re.findall(r"^\*\*Family:\*\* `([^`]+)`\.",text,re.MULTILINE)
    if len(family_labels) != 17 or set(family_labels) != set(FAMILIES):
        raise ValueError("human financial catalog omitted, duplicated or substituted a supported family")
    result = {"human_cases":65,"baseline_cases":45,"new_family_cases":17,"cross_family_cases":3}
    if sibling_pack is not None:
        coverage = json.loads((sibling_pack / "financial-capability-coverage.json").read_text())
        manifest = json.loads((sibling_pack / "product.json").read_text())
        declared = {f"financial-{family.replace('_','-')}" for family in FAMILIES}
        required = set(manifest["evaluation"]["required_capabilities"])
        if not declared <= required:
            raise ValueError("required feature capability missing")
        rows = coverage.get("cases",[])
        if len(rows)!=17 or {row.get("id") for row in rows}!=declared:
            raise ValueError("automated feature coverage inventory omitted or duplicated a family")
        for row in rows:
            if row.get("status")!="not_verified" or row.get("mapped") is not False or row.get("executed") is not False:
                raise ValueError("unexecuted feature declaration falsely claims automated coverage")
            scenario = json.loads((sibling_pack / "scenarios" / f"{row['id']}.json").read_text())
            if (scenario.get("id")!=row["id"] or scenario.get("covers")!=[row["id"]]
                    or scenario.get("required") is not True or scenario.get("verification")!="deterministic"):
                raise ValueError("feature scenario identity, requirement or independent verification differs")
        scenarios=list((sibling_pack / "scenarios").glob("*.json"))
        workflows=list((sibling_pack / "workflows").glob("*.json"))
        if len(scenarios)!=23 or len(workflows)!=5:
            raise ValueError("external declared catalog must retain11 existing plus17 added cases")
        result.update(external_declared_cases=28,external_new_unverified=17)
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("acceptance",type=Path,nargs="?",default=Path(__file__).parent)
    parser.add_argument("--sibling-pack",type=Path)
    args=parser.parse_args()
    print(json.dumps(check_catalog(args.acceptance,sibling_pack=args.sibling_pack),sort_keys=True))
