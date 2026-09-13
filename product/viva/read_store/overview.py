"""SQL-native composition of the current Overview contract.

The presentation composer is intentionally shared with the canonical surface;
this module supplies its financial inputs from one immutable read revision.
It never opens the event log, raw store, or constructs ``LedgerProjection``.
"""
from __future__ import annotations

import json
from decimal import Decimal

from ..ingest.brokerage import is_cash_row
from ..ledger.events import GRADES, Provenance
from ..ledger.projection.accounts import AccountInfo, account_info
from ..ledger.projection.balances import BalanceAnswer
from ..ledger.projection.movements import MovementInfo, is_expense
from ..ledger.projection.positions import ComposedValue, snapshot_positions
from ..ledger.projection.obligations import Obligation
from ..ledger.statements import AccountStatements, _record, _runs
from ..ingest.categorize import normalize_category
from merchantcore.taxonomy import subcategory_identity
from .held import _identity_core
from .store import ReadStoreError

MAX_OVERVIEW_ACCOUNTS = 200
MAX_OVERVIEW_OBSERVATIONS = 10_000
MAX_OVERVIEW_POSITIONS = 10_000
MAX_OVERVIEW_DOCUMENT_LINKS = 10_000
MAX_OVERVIEW_RULINGS = 10_000
MAX_OVERVIEW_RULING_BYTES = 1_000_000
MAX_OVERVIEW_MOVEMENTS = 10_000
MAX_ACTIVITY_RELATIONSHIPS = 10_000
MAX_ACTIVITY_PAGE = 100
MAX_ACTIVITY_TRANSFER_CANDIDATES = 200
MAX_ACTIVITY_TRANSFER_BYTES = 1_000_000
MAX_STATEMENT_REGISTER_ROWS = 10_000
MAX_STATEMENT_RESPONSE_BYTES = 1_000_000
CURRENT_EVIDENCE_BOUNDARY = "9999-12-31"


def _bounded(connection, sql, parameters, maximum, label):
    rows = connection.execute(sql + " LIMIT ?", (*parameters, maximum + 1)).fetchall()
    if len(rows) > maximum:
        raise ReadStoreError(f"{label} exceeds its {maximum}-row read bound")
    return rows


def _weakest(grades):
    values = tuple(grades)
    if not values or any(value not in GRADES for value in values):
        return ""
    return max(values, key=GRADES.index)


class SQLOverviewProjection:
    """The narrow projection protocol consumed by ``surface.overview``."""

    def __init__(self, revision, read_on: str, *, projected_as_of: str = "",
                 activity_evidence: bool = False,
                 statement_evidence: bool = False, locale: str = "en-US"):
        self._revision, self.connection = revision, revision.connection
        self._read_on = read_on
        self._locale = locale
        self._boundary = projected_as_of or CURRENT_EVIDENCE_BOUNDARY
        self.as_of = projected_as_of or None
        self.core = _identity_core(self.connection, self._boundary)
        self._states = self.core._acct
        self._balances = revision._goal_account_balances(
            as_of=self._boundary, limit=MAX_OVERVIEW_ACCOUNTS)
        self._load_measurement_history()
        self._movements = self._movement_view()
        self._tags, self._transfer_links, self._transfer_suggestions = {}, [], []
        self._statements = {}
        self._extra_account_ids = []
        if activity_evidence:
            self._load_activity_evidence()
        if statement_evidence:
            entity_rows = _bounded(
                self.connection,
                "SELECT account_id FROM account_entities ORDER BY account_id",
                (), MAX_OVERVIEW_ACCOUNTS, "Spending account identities")
            self._extra_account_ids = [row[0] for row in entity_rows
                                       if row[0] not in self._states]
            self._statements = self._load_statement_register()
        self._rulings = self._load_rulings()
        self._attribute_history = [row for row in self._rulings
                                   if row["scope"] == "attribute"]
        self._document_types, self._captured_documents = self._load_documents()

    def _load_measurement_history(self):
        from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
        for state in self._states.values():
            state.closings, state.position_history = [], {}
        observation_columns = (
            "account_id", "event_type", "occurred_at", "amount_text",
            "confirmed_by", "provenance_doc_id", "provenance_page",
            "provenance_region", "provenance_note", "source_sequence")
        selected, bounds = scalar_selected(
            observation_columns, ("provenance_page", "source_sequence"))
        observations = _bounded(
            self.connection,
            f"SELECT {selected} FROM balance_observations "
            "WHERE occurred_at<=? ORDER BY source_sequence",
            (*bounds, self._boundary), MAX_OVERVIEW_OBSERVATIONS,
            "Overview observation history")
        refuse_scalars(observations, observation_columns,
                       ("provenance_page", "source_sequence"),
                       label="Overview observation input")
        for account, event_type, occurred, amount, confirmed, doc, page, region, note, _seq in observations:
            state = self._states.get(account)
            if state is None:
                continue
            if event_type == "ClosingBalanceObserved":
                grade = "verified" if confirmed == "human" else "corroborated"
                state.closings.append((occurred, Decimal(amount), grade, doc))
        position_columns = (
            "account_id", "occurred_at", "instrument_id", "quantity_text",
            "value_text", "currency", "cost_basis_text", "valuation_class",
            "grade", "provenance_doc_id", "provenance_page",
            "provenance_region", "provenance_note", "source_sequence")
        selected, bounds = scalar_selected(
            position_columns, ("provenance_page", "source_sequence"))
        positions = _bounded(
            self.connection,
            f"SELECT {selected} FROM positions "
            "WHERE occurred_at<=? ORDER BY source_sequence",
            (*bounds, self._boundary), MAX_OVERVIEW_POSITIONS,
            "Overview position history")
        refuse_scalars(positions, position_columns,
                       ("provenance_page", "source_sequence"),
                       label="Overview position input")
        for account, occurred, instrument, units, value, currency, basis, valuation, grade, doc, page, region, note, _seq in positions:
            state = self._states.get(account)
            if state is None:
                continue
            state.position_history.setdefault(instrument, []).append({
                "units": Decimal(units), "market_value": Decimal(value),
                "currency": currency, "as_of": occurred,
                "cost_basis": None if basis == "" else Decimal(basis),
                "valuation_class": valuation, "grade": grade,
                "provenance": Provenance(doc, page, region, note),
                "is_cash": is_cash_row(instrument),
            })

    def _movement_view(self):
        from .scalar_bounds import selected as scalar_selected, refuse as refuse_scalars
        output = []
        names = ("movement_key", "account_id", "account_kind", "occurred_at",
                 "amount_text", "grade", "currency", "description",
                 "provenance_doc_id", "provenance_page", "provenance_region",
                 "provenance_note", "linked", "nature", "nature_reason",
                 "provisional", "ruling_account", "merchant_key", "category",
                 "subcategory", "category_grade", "subcategory_grade",
                 "category_by", "subcategory_by")
        selected, bounds = scalar_selected(
            names, ("provenance_page", "linked", "provisional"))
        rows = self.connection.execute(
            f"SELECT {selected} FROM movements "
            "INDEXED BY movements_by_activity_order "
            "ORDER BY occurred_at DESC,movement_key DESC LIMIT ?",
            (*bounds, MAX_OVERVIEW_MOVEMENTS + 1,)).fetchall()
        if len(rows) > MAX_OVERVIEW_MOVEMENTS:
            raise ReadStoreError(
                f"Overview movement history exceeds its {MAX_OVERVIEW_MOVEMENTS}-row read bound")
        refuse_scalars(rows, names,
                       ("provenance_page", "linked", "provisional"),
                       label="Overview movement input")
        self._movement_grades, self._categories, self._merchant_keys = {}, {}, {}
        for values in rows:
            row = dict(zip(names, values))
            category_grade, subcategory_grade = (row["category_grade"],
                                                  row["subcategory_grade"])
            grades = [value for value in (category_grade, subcategory_grade)
                      if value]
            if row["category"]:
                self._categories[row["movement_key"]] = {
                    "category": row["category"], "subcategory": row["subcategory"],
                    "category_grade": category_grade,
                    "subcategory_grade": subcategory_grade,
                    "category_by": row["category_by"],
                    "subcategory_by": row["subcategory_by"],
                    "grade": _weakest(grades),
                    "by": (row["category_by"]
                           if row["category_by"] == row["subcategory_by"]
                           or not row["subcategory_by"] else "mixed"),
                }
            self._movement_grades[row["movement_key"]] = row["grade"]
            self._merchant_keys[row["movement_key"]] = row["merchant_key"]
            output.append(MovementInfo(
                key=row["movement_key"], account=row["account_id"],
                kind=row["account_kind"], date=row["occurred_at"],
                amount=Decimal(row["amount_text"]), description=row["description"],
                currency=row["currency"], provenance=Provenance(
                    row["provenance_doc_id"], row["provenance_page"],
                    row["provenance_region"], row["provenance_note"]),
                linked=bool(row["linked"]), nature=row["nature"],
                nature_reason=row["nature_reason"],
                provisional=bool(row["provisional"]),
                ruling_account=row["ruling_account"]))
        return output

    def _load_activity_evidence(self):
        tag_rows = _bounded(
            self.connection,
            "SELECT movement_key,tag,source FROM movement_tags "
            "ORDER BY movement_key,source,tag", (), MAX_ACTIVITY_RELATIONSHIPS,
            "Activity tag evidence")
        self._tags = {}
        for key, tag, source in tag_rows:
            self._tags.setdefault((key, source), []).append(tag)
        alias_rows = _bounded(
            self.connection,
            "SELECT subject,same_as FROM ruling_history "
            "WHERE scope='category' AND same_as<>'' ORDER BY source_sequence",
            (), MAX_ACTIVITY_RELATIONSHIPS, "Activity category aliases")
        self._category_alias_rows = list(alias_rows)
        link_rows = _bounded(
            self.connection,
            "SELECT movement_a,movement_b,grade,by_actor,decided_by "
            "FROM transfer_links ORDER BY movement_a,movement_b", (),
            MAX_ACTIVITY_RELATIONSHIPS, "Activity transfer links")
        self._transfer_links = [
            {"a": a, "b": b, "grade": grade, "by": actor,
             "decided_by": decided}
            for a, b, grade, actor, decided in link_rows]
        suggestion_rows = _bounded(
            self.connection,
            "SELECT movement_a,"
            "CASE WHEN length(CAST(candidates_json AS BLOB))<=? THEN candidates_json END,"
            "CASE WHEN length(CAST(evidence_json AS BLOB))<=? THEN evidence_json END "
            "FROM transfer_suggestions ORDER BY movement_a",
            (MAX_ACTIVITY_TRANSFER_BYTES, MAX_ACTIVITY_TRANSFER_BYTES),
            MAX_ACTIVITY_RELATIONSHIPS, "Activity transfer suggestions")
        self._transfer_suggestions = []
        for source, candidates, evidence in suggestion_rows:
            if (not isinstance(candidates, str) or not isinstance(evidence, str)
                    or len(candidates.encode("utf-8")) > MAX_ACTIVITY_TRANSFER_BYTES
                    or len(evidence.encode("utf-8")) > MAX_ACTIVITY_TRANSFER_BYTES):
                raise ReadStoreError("Activity transfer evidence exceeds its byte bound")
            try:
                from .transfer_payload import (candidate_keys,
                                               decode as decode_transfer)
                decoded_candidates = candidate_keys(
                    decode_transfer(candidates, list,
                                    maximum_bytes=MAX_ACTIVITY_TRANSFER_BYTES),
                    maximum_count=MAX_ACTIVITY_TRANSFER_CANDIDATES)
                decoded_evidence = decode_transfer(
                    evidence, dict, maximum_bytes=MAX_ACTIVITY_TRANSFER_BYTES)
            except (TypeError, ValueError) as exc:
                raise ReadStoreError("Activity transfer evidence is invalid") from exc
            if not isinstance(decoded_candidates, list) or not isinstance(decoded_evidence, dict):
                raise ReadStoreError("Activity transfer evidence has the wrong shape")
            self._transfer_suggestions.append(
                {"a": source, "candidates": decoded_candidates,
                 "evidence": decoded_evidence})

    def _load_statement_register(self):
        rows = _bounded(
            self.connection,
            "SELECT p.doc_id,p.account_id,d.doc_type,"
            "CASE WHEN length(CAST(r.response_text AS BLOB))<=? "
            "THEN r.response_text ELSE NULL END,"
            "p.period_end,p.closing_amount_text,p.source_sequence "
            "FROM statement_periods p INDEXED BY statement_periods_by_account_date "
            "JOIN documents d INDEXED BY documents_by_doc ON d.doc_id=p.doc_id "
            "JOIN document_reads r INDEXED BY document_reads_by_doc_phase_source "
            "ON r.doc_id=p.doc_id AND r.phase='extract' "
            "AND r.parse_ok=1 "
            "WHERE NOT EXISTS (SELECT 1 FROM documents newer "
            "WHERE newer.doc_id=d.doc_id AND newer.source_sequence>d.source_sequence) "
            "AND NOT EXISTS (SELECT 1 FROM statement_periods newer "
            "WHERE newer.doc_id=p.doc_id AND newer.account_id=p.account_id "
            "AND newer.source_sequence>p.source_sequence) "
            "AND NOT EXISTS (SELECT 1 FROM document_reads newer "
            "WHERE newer.doc_id=r.doc_id AND newer.phase='extract' "
            "AND newer.parse_ok=1 AND newer.source_sequence>r.source_sequence) "
            "ORDER BY p.account_id DESC,p.period_end,p.source_sequence",
            (MAX_STATEMENT_RESPONSE_BYTES,), MAX_STATEMENT_REGISTER_ROWS,
            "statement evidence register")
        by_account = {}
        seen = set()
        from ..ingest.registry import BALANCE_IDENTITY, profile_for
        from ..ingest.statement import period_from_model_json
        for doc, account, doc_type, response, closing_date, closing, _seq in rows:
            if response is None:
                raise ReadStoreError("statement response exceeds its byte bound")
            identity = (doc, account)
            if identity in seen:
                raise ReadStoreError("statement evidence register is ambiguous")
            seen.add(identity)
            profile = profile_for(doc_type)
            state = self._states.get(account)
            if profile is None or profile.identity != BALANCE_IDENTITY or state is None:
                continue
            try:
                period = period_from_model_json(
                    response, self._locale, state.currency or "USD")
            except Exception as exc:
                raise ReadStoreError("statement evidence register is invalid") from exc
            if period is None:
                continue
            record = _record(doc, account, period,
                             (Decimal(closing), closing_date))
            if record is not None:
                by_account.setdefault(account, []).append(record)
        return {account: AccountStatements(account, records, _runs(records))
                for account, records in by_account.items()}

    def _load_rulings(self):
        rows = _bounded(
            self.connection,
            "SELECT scope,subject,CASE WHEN length(CAST(legs_json AS BLOB))<=? "
            "THEN legs_json ELSE NULL END,by_actor,grade,said,value_text,currency,"
            "occurred_at,source_sequence FROM ruling_history WHERE occurred_at<=?"
            " ORDER BY source_sequence", (MAX_OVERVIEW_RULING_BYTES, self._boundary),
            MAX_OVERVIEW_RULINGS,
            "Overview ruling history")
        out = []
        for scope_, subject, legs, actor, grade, said, value, currency, occurred, sequence in rows:
            if legs is None:
                raise ReadStoreError("Overview ruling legs exceed their byte bound")
            out.append({"scope": scope_, "subject": subject, "legs": json.loads(legs),
                        "by": actor, "grade": grade, "said": said, "value": value,
                        "currency": currency, "occurred_at": occurred,
                        "source_sequence": sequence})
        return out

    def _load_documents(self):
        documents = _bounded(
            self.connection,
            "SELECT doc_id,filename,doc_type FROM documents WHERE occurred_at<=? "
            "ORDER BY source_sequence", (self._boundary,),
            MAX_OVERVIEW_DOCUMENT_LINKS,
            "Overview document history")
        links = _bounded(
            self.connection,
            "SELECT h.account_id,d.doc_type FROM document_account_history h "
            "JOIN documents d ON d.doc_id=h.doc_id WHERE h.occurred_at<=? "
            "AND d.occurred_at<=? ORDER BY h.source_sequence,h.account_index",
            (self._boundary, self._boundary),
            MAX_OVERVIEW_DOCUMENT_LINKS, "Overview account-document history")
        captured = {doc_id: filename for doc_id, filename, _type in documents}
        types = {}
        for account, doc_type in links:
            if doc_type:
                types.setdefault(account, set()).add(doc_type)
        return types, captured

    def accounts(self):
        return sorted(account for account, state in self._states.items()
                      if state.seen)

    def account_infos(self):
        return ([account_info(self.core, account) for account in self.accounts()]
                + [AccountInfo(account=account)
                   for account in self._extra_account_ids])

    def account_info(self, account):
        return account_info(self.core, account)

    def account_aliases(self):
        return dict(self.core._aliases)

    def _state(self, account):
        return self._states[account]

    def balance(self, account):
        row = self._balances[account]
        provenance = row["provenance"]
        return BalanceAnswer(account, row["amount"], row["grade"], self.as_of,
            Provenance(provenance["doc_id"], provenance["page"], provenance["region"], provenance["note"]),
            None, row["explanation"], row["currency"], row["dated"])

    def composed_values(self, account, as_of=""):
        boundary = as_of or self._boundary
        state, balance = self._states[account], self._balances.get(account)
        terms = []
        if as_of:
            eligible = [row for row in getattr(state, "closings", ()) if row[0] <= as_of]
            if eligible:
                occurred, amount, grade, doc = max(eligible, key=lambda row: row[0])
                terms.append((amount, state.currency, occurred, grade, doc))
        elif balance is not None:
            terms.append((balance["amount"], balance["currency"], balance["dated"],
                          balance["grade"], balance["provenance"]["doc_id"]))
        history = getattr(state, "position_history", {})
        for cash in (True, False):
            for item in snapshot_positions(state, boundary, cash=cash).values():
                terms.append((item["market_value"], item["currency"] or state.currency,
                              item["as_of"], item["grade"], ""))
        grouped = {}
        for amount, currency, dated, grade, doc in terms:
            item = grouped.setdefault(currency, {"amount": Decimal(0), "dates": set(), "grades": [], "proves": ""})
            item["amount"] += amount
            if dated: item["dates"].add(dated)
            item["grades"].append(grade); item["proves"] = item["proves"] or doc
        return [ComposedValue(account, row["amount"], currency, tuple(sorted(row["dates"])),
                              _weakest(row["grades"]), row["proves"])
                for currency, row in sorted(grouped.items())]

    def movements(self):
        return list(self._movements)

    def spending_by_currency(self):
        output = {}
        for movement in self._movements:
            if is_expense(movement) and movement.nature == "spending":
                output[movement.currency] = output.get(movement.currency, Decimal(0)) + abs(movement.amount)
        return output

    def rulings(self, scope=None):
        return [row for row in self._rulings
                if scope is None or row["scope"] == scope]

    def document_types_of(self, account):
        return set(self._document_types.get(account, ()))

    def open_holds(self):
        return self._revision.held_items(as_of=self._boundary)

    def obligations(self, today):
        return [Obligation(**row) for row in self._revision.obligations(today=today)]

    def findings(self, today):
        return self._revision.findings(today=today)

    def open_questions(self, *, limit, as_of, jurisdiction, locale):
        return self._revision.open_questions(
            limit=limit, as_of=as_of, jurisdiction=jurisdiction,
            locale=locale)

    def current_period(self, today):
        return self._revision.current_period(
            today=today, evidence_as_of=self._boundary)

    def captured_docs(self):
        return list(self._captured_documents)

    def captured_filenames(self):
        return dict(self._captured_documents)

    def movement_grades(self):
        return dict(self._movement_grades)

    @staticmethod
    def _is_expense(movement):
        return is_expense(movement)

    def statements(self, account):
        return self._statements.get(account)

    def derived_category(self, movement):
        record = self._categories.get(movement.key)
        return dict(record) if record is not None else None

    def tags_of(self, movement):
        return list(self._tags.get((movement.key, "movement"), ()))

    def inherited_tags_of(self, movement):
        return list(self._tags.get((movement.key, "merchant"), ()))

    def linked_keys(self):
        return {key for row in self._transfer_links for key in (row["a"], row["b"])}

    def transfer_links(self):
        return [dict(row) for row in self._transfer_links]

    def transfer_suggestions(self):
        return [dict(row) for row in self._transfer_suggestions]

    def activity_page(self, limit: int, focus: str = ""):
        """Select pending-first Activity identities with an exact tail count."""
        if (not isinstance(limit, int) or isinstance(limit, bool)
                or not 1 <= limit <= MAX_ACTIVITY_PAGE):
            raise ReadStoreError(
                f"Activity limit must be between 1 and {MAX_ACTIVITY_PAGE}")
        pending = self.connection.execute(
            "SELECT m.movement_key FROM movements m "
            "INDEXED BY movements_by_activity_order "
            "JOIN transfer_suggestions s ON s.movement_a=m.movement_key "
            "ORDER BY m.occurred_at DESC,m.movement_key DESC LIMIT ?",
            (limit,)).fetchall()
        remaining = limit - len(pending)
        ordinary = self.connection.execute(
            "SELECT m.movement_key FROM movements m "
            "INDEXED BY movements_by_activity_order "
            "LEFT JOIN transfer_suggestions s ON s.movement_a=m.movement_key "
            "WHERE s.movement_a IS NULL "
            "ORDER BY m.occurred_at DESC,m.movement_key DESC LIMIT ?",
            (remaining,)).fetchall()
        keys = [row[0] for row in (*pending, *ordinary)]
        if focus and focus not in keys:
            found = self.connection.execute(
                "SELECT movement_key FROM movements WHERE movement_key=?",
                (focus,)).fetchone()
            if found is not None:
                keys = [*keys[:-1], focus] if keys else [focus]
        by_key = {movement.key: movement for movement in self._movements}
        selected = [by_key[key] for key in keys if key in by_key]
        total = self.connection.execute("SELECT COUNT(*) FROM movements").fetchone()[0]
        return selected, max(0, total - len({item.key for item in selected}))

    def merchant_categories(self):
        return {merchant: self._categories[key]
                for key, merchant in self._merchant_keys.items()
                if merchant and key in self._categories}

    def known_categories(self):
        return sorted({row["category"] for row in self._categories.values()
                       if row["category"]})

    def known_tags(self):
        return sorted({tag for values in self._tags.values() for tag in values})

    def _canonical_label(self, label, identity):
        start = identity(label)
        current, seen, aliases, collisions = start, set(), {}, set()
        for raw, target in getattr(self, "_category_alias_rows", ()):
            key, value = identity(raw), identity(target)
            if key == value:
                continue
            if key in aliases and aliases[key] != value:
                collisions.add(key)
            else:
                aliases[key] = value
        if current not in aliases:
            return start
        while current in aliases:
            if current in seen or current in collisions:
                return start
            seen.add(current)
            current = aliases[current]
        return start if current in collisions else current

    def canonical_category(self, label):
        return self._canonical_label(label, normalize_category)

    def canonical_subcategory(self, label):
        return self._canonical_label(label, subcategory_identity)


def projection(revision, *, today: str):
    """Return the bounded SQL-backed input consumed by the surface composer."""
    return SQLOverviewProjection(revision, today)


class SQLHistoricalOverviewProjection(SQLOverviewProjection):
    """Value-time Overview inputs from one held normalized SQL revision."""

    def __init__(self, revision, *, as_of: str, today: str):
        self._historical_as_of = as_of
        super().__init__(revision, today, projected_as_of=as_of)

    def _movement_view(self):
        from .temporal_activity import SQLHistoricalActivityProjection
        self._activity = SQLHistoricalActivityProjection(
            self._revision, self._historical_as_of)
        self._movement_grades = self._activity.movement_grades()
        return self._activity.movements()

    def obligations(self, today):
        from .rhythm import obligations
        return [Obligation(**row) for row in obligations(
            self.connection, today=today, evidence_as_of=self._boundary)]

    def findings(self, today):
        from ..ledger.projection.merchants import merchant_key_of
        from .composition import findings
        rows = []
        for movement in self._movements:
            category = self._activity.derived_category(movement) or {}
            rows.append((
                movement.key, int(movement.linked), movement.nature,
                category.get("category", ""),
                merchant_key_of(self._activity._core, movement),
                movement.account, movement.date, str(movement.amount),
                movement.currency, movement.description, movement.kind,
                movement.provenance.doc_id,
                self._movement_grades.get(movement.key, "")))
        return findings(self.connection, today=today,
                        evidence_as_of=self._boundary, historical_rows=rows)
