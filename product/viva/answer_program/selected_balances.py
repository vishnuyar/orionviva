"""Fixed selected-account semantics and data-blind report lowering."""

PARAMETERS = tuple(f"account_phrase_{i}" for i in range(1, 8))
CLAIMS = ("account_report",)


def family():
    from .intents import SemanticFamily, _object, _STRING
    return SemanticFamily("selected_account_balances",
        _object({name: _STRING for name in PARAMETERS}, PARAMETERS[:2]),
        CLAIMS, build, user_label="dated amounts and evidence for selected accounts",
        user_example="show dated amounts, source pages, recorded restrictions and unavailable closure status for two through seven individually selected accounts")


def resolve(registry, outcome):
    from dataclasses import replace
    from .intents import SemanticOutcome
    from .schema import ContractError
    request = outcome.request
    p = request.parameters
    if set(p) != set(PARAMETERS[:len(p)]) or not 2 <= len(p) <= 7:
        raise ContractError("selected account selectors require a contiguous prefix of two through seven")
    resolved = {}
    kinds = {}
    for name in PARAMETERS[:len(p)]:
        candidates = registry._account_role_candidates(p[name])
        if len(candidates) != 1:
            return SemanticOutcome("clarify", detail={"tag":"ambiguous_account",
                "question":"Which selected account do you mean?",
                "options":registry._named_account_options(candidates)})
        candidate = candidates[0]
        if candidate["kind"] not in {"depository", "investment", "liability"}:
            raise ContractError("selected identity is not a balance account")
        proof = (request.parameter_sources or {}).get(name, {})
        quoted = registry._account_role_candidates(str(proof.get("quote") or ""))
        if quoted and (len(quoted) != 1 or quoted[0]["id"] != candidate["id"]):
            raise ContractError("selected account proof crosses account identities")
        resolved[name] = candidate["id"]
        kinds[candidate["id"]] = candidate["kind"]
    if len(set(resolved.values())) != len(resolved):
        raise ContractError("selected account identities repeat")
    return SemanticOutcome("request", replace(request, parameters=resolved)), kinds


def build(request, manifest, kinds):
    from .intents import _program, _read, _rows_clause, _rows_binding
    accounts = tuple(request.parameters[name] for name in PARAMETERS[:len(request.parameters)])
    nodes = [_read("selected_balances", "read_account_balance_report",
        {f"account_{i}":account for i,account in enumerate(accounts,1)})]
    clauses, bindings = [], []
    for quantity, label in (("balance", "Selected account amounts"), ("owed", "Selected amounts owed")):
        if any(("owed" if kinds[account] == "liability" else "balance") == quantity for account in accounts):
            clauses.append(_rows_clause(quantity, label + ": {" + quantity + "}.", quantity))
            bindings.append(_rows_binding(quantity, "selected_balances", quantity=quantity))
    for i,account in enumerate(accounts):
        letter = chr(97+i)
        hole = "restriction_" + letter
        account_hole = "restriction_account_" + letter
        clauses.append({"id":hole, "text":"Recorded restriction for {"+account_hole+"}: {"+hole+"}.",
            "slots":[{"name":account_hole,"type":"account"}, {"name":hole,"type":"instrument_normalized"}]})
        bindings.append({"hole":account_hole,"source":"identity_"+letter,"reference_kind":"entity",
            "selector":{"entity_kind":"account","cardinality":"one"}})
        bindings.append({"hole":hole,"source":"selected_balances","reference_kind":"instrument_normalized",
            "selector":{"cardinality":"one","claim":"availability_restriction","entity_ref":{"id":account}}})
        nodes.append({"id":"identity_"+letter,"kind":"resolve_entity","depends_on":["selected_balances"],
            "importance":"required","entity_kind":"account","phrase":account})
    holes = ["account_" + chr(97+i) for i in range(len(accounts))]
    clauses.append({"id":"closure","text":"Accepted records do not establish closure status for "
        + ", ".join("{"+hole+"}" for hole in holes) + ".",
        "slots":[{"name":hole,"type":"account"} for hole in holes]})
    bindings.extend({"hole":hole,"source":"identity_"+chr(97+i),"reference_kind":"entity",
        "selector":{"entity_kind":"account","cardinality":"one"}} for i,hole in enumerate(holes))
    return _program(manifest, request.family, clauses, nodes, bindings,
        required=["closure"], allow_partial=True)
