"""Deterministic DAG execution of a validated AnswerProgram."""

from __future__ import annotations

import copy
import json
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from dataclasses import dataclass, field

from ..tools.envelope import ToolResult, refusal
from .evidence import EvidenceGraph
from .schema import AnswerProgram, AnswerResourcePolicy, ProgramNode


@dataclass
class NodeExecution:
    node_id: str
    status: str
    tool: str = ""
    elapsed_ms: int = 0
    memoized_from: str = ""
    refusal: str = ""
    values: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {"node_id": self.node_id, "status": self.status, "tool": self.tool,
                "elapsed_ms": self.elapsed_ms, "memoized_from": self.memoized_from,
                "refusal": self.refusal, "values": dict(self.values)}


@dataclass
class ExecutionResult:
    graph: EvidenceGraph
    transcript: list[ToolResult]
    nodes: dict[str, NodeExecution]
    deadline_exceeded: bool = False
    evidence_limit_exceeded: bool = False
    figure_limit_exceeded: bool = False

    def to_dict(self) -> dict:
        return {"nodes": [item.to_dict() for item in self.nodes.values()],
                "deadline_exceeded": self.deadline_exceeded,
                "evidence_limit_exceeded": self.evidence_limit_exceeded,
                "figure_limit_exceeded": self.figure_limit_exceeded,
                "evidence_bytes": self.graph.size_bytes}


class ProgramExecutor:
    """Execute only a program already admitted by ProgramValidator."""

    def __init__(self, registry, policy: AnswerResourcePolicy, *, query_executor=None,
                 max_workers: int = 8):
        self.registry = registry
        self.policy = policy
        self.query_executor = query_executor
        self.max_workers = max(1, max_workers)

    def execute(self, program: AnswerProgram, question: str) -> ExecutionResult:
        runtime=getattr(self.registry,"instrument_runtime",None)
        if runtime is not None and any(node.tool in {"read_instrument_details", "read_account_balance_report"} or (node.tool in {"read_investment_evidence","read_retirement_funding"} and runtime.supplier is not None) for node in program.nodes):
            deadline=time.monotonic()+self.policy.max_execution_ms/1000
            with runtime.execution(deadline,question=question):
                if runtime.revision is None or not runtime.source_is_current():
                    return self._source_unavailable(program,question)
                execution=self._execute(program,question,deadline_override=deadline)
                selected = any(node.tool == "read_account_balance_report" for node in program.nodes)
                current = getattr(self.registry, "selected_balance_source_current", lambda: False)
                return execution if (runtime.source_is_current() and (not selected or current())) else self._source_unavailable(program,question)
        return self._execute(program,question)

    def _selected_report_unavailable(self, program, question, produced, tag, text, payload_bytes):
        failed = refusal("read_account_balance_report", tag, text,
            trace=copy.deepcopy(produced.data["trace"]), complete_payload_bytes=payload_bytes)
        return ExecutionResult(EvidenceGraph(question), [failed],
            {node.id:NodeExecution(node.id, "refused" if node.tool == "read_account_balance_report" else "dependency_blocked",
                tool=node.tool, refusal=tag if node.tool == "read_account_balance_report" else "dependency_failed")
             for node in program.nodes})

    def _source_unavailable(self,program,question):
        return ExecutionResult(EvidenceGraph(question),
            [refusal("read_instrument_details","current_data_unavailable","The current source changed or is unavailable.")],
            {node.id:NodeExecution(node.id,"refused",tool=node.tool,refusal="current_data_unavailable") for node in program.nodes})

    def _execute(self, program: AnswerProgram, question: str, *, deadline_override=None) -> ExecutionResult:
        graph = EvidenceGraph(question)
        graph.ground.instrument_token=getattr(getattr(self.registry,"instrument_runtime",None),"run_token",None)
        transcript: list[ToolResult] = []
        records: dict[str, NodeExecution] = {}
        results: dict[str, ToolResult] = {}
        fingerprints: dict[str, str] = {}
        pending = list(program.nodes)
        started = time.monotonic()
        deadline = deadline_override or (started + self.policy.max_execution_ms / 1000)
        deadline_exceeded = False
        evidence_limit_exceeded = False
        figure_limit_exceeded = False

        while pending:
            ready = [node for node in pending
                     if all(dep in records for dep in node.depends_on)]
            if not ready:
                break
            # Required work is admitted and completed before supporting work,
            # and supporting before optional.  Within one class every ready
            # node is one atomic parallel wave.
            rank = {"required": 0, "supporting": 1, "optional": 2}
            stage = min(rank[node.importance] for node in ready)
            ready = [node for node in ready if rank[node.importance] == stage]
            ready_ids = {node.id for node in ready}
            pending = [node for node in pending if node.id not in ready_ids]

            runnable = []
            for node in ready:
                failed = [dep for dep in node.depends_on
                          if records[dep].status not in ("completed", "memoized")]
                if failed:
                    records[node.id] = NodeExecution(
                        node.id, "dependency_blocked", refusal="dependency_failed")
                else:
                    runnable.append(node)
            if not runnable:
                continue
            if time.monotonic() >= deadline:
                deadline_exceeded = True
                for node in runnable:
                    records[node.id] = NodeExecution(
                        node.id, "skipped", refusal="execution_deadline")
                continue

            calls = []
            scheduled: dict[str, str] = {}
            aliases: list[tuple[ProgramNode, str]] = []
            for node in runnable:
                args, problem = self._resolved(node.args, records)
                if problem:
                    result = refusal(node.tool or node.kind, "invalid_reference", problem)
                    calls.append((node, result, "", 0))
                    continue
                fingerprint = self._fingerprint(node, args)
                if fingerprint and fingerprint in fingerprints:
                    source = fingerprints[fingerprint]
                    graph.attach(node.id, source)
                    results[node.id] = results[source]
                    records[node.id] = NodeExecution(
                        node.id, "memoized", tool=node.tool,
                        memoized_from=source,
                        values=dict(records[source].values))
                    continue
                if fingerprint and fingerprint in scheduled:
                    aliases.append((node, scheduled[fingerprint]))
                    continue
                if fingerprint:
                    scheduled[fingerprint] = node.id
                calls.append((node, args, fingerprint, None))

            actual = [(node, args, fingerprint) for node, args, fingerprint, marker
                      in calls if marker is None]
            completed = {}
            # SQLCipher connections remain on their creating thread. Instrument
            # nodes share one pinned immutable revision across all DAG waves.
            parallel=[item for item in actual if item[0].tool not in {"read_instrument_details","read_investment_evidence","read_retirement_funding","read_account_balance_report"}]
            for node,args,fingerprint in actual:
                if node.tool in {"read_instrument_details","read_investment_evidence","read_retirement_funding","read_account_balance_report"}:
                    began=time.monotonic()
                    result=(refusal(node.tool,"execution_deadline","The admitted execution deadline expired.")
                            if began>=deadline else self._run_node(node,args,graph,records))
                    completed[node.id]=(node,result,fingerprint,int((time.monotonic()-began)*1000))
            if parallel:
                pool = ThreadPoolExecutor(max_workers=min(self.max_workers,
                                                          len(parallel)))
                futures = {node.id: (node, fingerprint, time.monotonic(),
                                     pool.submit(self._run_node, node, args,
                                                 graph, records))
                           for node, args, fingerprint in parallel}
                timed_out = False
                for node_id, (node, fingerprint, began, future) in futures.items():
                    remaining = max(0, deadline - time.monotonic())
                    try:
                        result = future.result(timeout=remaining)
                    except TimeoutError:
                        timed_out = deadline_exceeded = True
                        result = refusal(node.tool or node.kind,
                                         "execution_deadline",
                                         "The admitted execution deadline expired.")
                    completed[node_id] = (
                        node, result, fingerprint,
                        int((time.monotonic() - began) * 1000))
                pool.shutdown(wait=not timed_out, cancel_futures=timed_out)

            immediate = [(node, args, fingerprint, 0) for node, args, fingerprint, marker
                         in calls if marker == 0]
            for node, result, fingerprint, elapsed in [
                    *(completed[node.id] for node, _, _ in actual), *immediate]:
                if result.ok:
                    try:graph.stamp(node.id, result)
                    except ValueError:
                        from ..instrument_claims import DEDICATED_QUANTITIES
                        if not (result.instrument_assertions or result.instrument_premises or any(f.get("claim") or f.get("quantity") in DEDICATED_QUANTITIES for f in result.figures)):raise
                        result=refusal(node.tool or node.kind,"instrument_authority_required","The result has no valid current-run instrument authority.")
                    if result.ok and node.tool == "read_account_balance_report":
                        from ..tools.account_balances import complete_bytes
                        runtime = self.registry.instrument_runtime
                        source_deadline = min(runtime.deadline, runtime.started + 2)
                        payload_bytes = complete_bytes(result)
                        if payload_bytes > 50_000 or time.monotonic() >= source_deadline:
                            return self._selected_report_unavailable(program, question, result,
                                "resource_limit", "The complete selected-account report exceeds its read bound.", payload_bytes)
                        if not self.registry.selected_balance_source_current():
                            return self._selected_report_unavailable(program, question, result,
                                "current_data_unavailable", "The selected account source changed during serialization.", payload_bytes)
                        if time.monotonic() >= source_deadline:
                            return self._selected_report_unavailable(program, question, result,
                                "resource_limit", "The complete selected-account report exceeds its read bound.", payload_bytes)
                    if result.ok and fingerprint:
                        fingerprints[fingerprint] = node.id
                results[node.id] = result
                transcript.append(result)
                status = "completed" if result.ok else "refused"
                # Stamping assigns stable ids to figures and identifiers.  A
                # symbolic value may therefore be exported only afterwards.
                values = self._values(result)
                records[node.id] = NodeExecution(
                    node.id, status, tool=node.tool or node.kind,
                    elapsed_ms=elapsed, refusal=result.refusal, values=values)

            for node, source in aliases:
                if (source not in records
                        or records[source].status not in ("completed", "memoized")):
                    records[node.id] = NodeExecution(
                        node.id, "dependency_blocked", tool=node.tool,
                        refusal="memoized_source_failed")
                    continue
                graph.attach(node.id, source)
                results[node.id] = results[source]
                source_record = records[source]
                records[node.id] = NodeExecution(
                    node.id, "memoized", tool=node.tool,
                    memoized_from=source, values=dict(source_record.values),
                    refusal=source_record.refusal)

            if graph.size_bytes > self.policy.max_evidence_bytes:
                evidence_limit_exceeded = True
                for node in pending:
                    records[node.id] = NodeExecution(
                        node.id, "skipped", refusal="evidence_limit")
                pending = []
            if len(graph.book) > self.policy.max_figures:
                figure_limit_exceeded = True
                for node in pending:
                    records[node.id] = NodeExecution(
                        node.id, "skipped", refusal="figure_limit")
                pending = []
            if time.monotonic() >= deadline and pending:
                deadline_exceeded = True
                for node in pending:
                    records[node.id] = NodeExecution(
                        node.id, "skipped", refusal="execution_deadline")
                pending = []

        return ExecutionResult(graph, transcript, records, deadline_exceeded,
                               evidence_limit_exceeded, figure_limit_exceeded)

    @staticmethod
    def _resolved(value, records):
        if isinstance(value, dict):
            if set(value) == {"ref"}:
                ref = value["ref"]
                record = records.get(str(ref.get("node")))
                name = str(ref.get("value") or "")
                if record is None or name not in record.values:
                    return None, (f"symbolic value {name!r} from "
                                  f"{ref.get('node')!r} is unavailable")
                return copy.deepcopy(record.values[name]), ""
            out = {}
            for key, child in value.items():
                resolved, problem = ProgramExecutor._resolved(child, records)
                if problem:
                    return None, problem
                out[key] = resolved
            return out, ""
        if isinstance(value, list):
            out = []
            for child in value:
                resolved, problem = ProgramExecutor._resolved(child, records)
                if problem:
                    return None, problem
                out.append(resolved)
            return out, ""
        return value, ""

    @staticmethod
    def _fingerprint(node, args) -> str:
        if node.kind not in ("tool_read", "compute"):
            return ""
        return json.dumps({"tool": node.tool or "compute", "args": args},
                          sort_keys=True, separators=(",", ":"), default=str)

    def _run_node(self, node: ProgramNode, args, graph, records) -> ToolResult:
        if node.kind in ("tool_read", "compute"):
            return self.registry.call(node.tool or "compute", args,
                                      figures=graph.book,
                                      question=graph.question)
        if node.kind == "resolve_entity":
            return self._resolve_entity(node, graph)
        if node.kind == "financial_query":
            if self.query_executor is None:
                return refusal("financial_query", "unsupported_operation",
                               "No admitted financial query executor is installed.")
            return self.query_executor.execute(node.query, graph)
        if node.kind == "conditional":
            return self._conditional(node, records)
        return refusal(node.kind, "unsupported_operation",
                       "The program node kind is not executable.")

    @staticmethod
    def _resolve_entity(node, graph) -> ToolResult:
        phrase = " ".join(node.phrase.casefold().split())
        matches = []
        for item in graph.ground.entities.values():
            if item.get("kind") != node.entity_kind:
                continue
            values = {" ".join(str(value).casefold().split())
                      for key, value in item.items()
                      if key not in ("id", "kind") and isinstance(value, str)}
            if phrase in values:
                matches.append(item)
        if len(matches) != 1:
            return refusal("resolve_entity", "ambiguous_entity" if matches
                           else "missing_entity",
                           "The entity phrase did not resolve uniquely.")
        return ToolResult(tool="resolve_entity", ok=True,
                          identifiers=[dict(matches[0])], data={"resolved": True})

    @staticmethod
    def _conditional(node, records) -> ToolResult:
        predicate = node.predicate
        kind = predicate.get("kind")
        source = records.get(str(predicate.get("node") or ""))
        if kind == "result_nonempty":
            value = bool(source and source.values.get("result_nonempty"))
        elif kind == "resolved_unique":
            value = bool(source and source.values.get("unique_entity_key"))
        else:
            return refusal("conditional", "unsupported_predicate",
                           "The conditional predicate is not admitted.")
        return ToolResult(tool="conditional", ok=True, data={"condition": value})

    @staticmethod
    def _values(result: ToolResult) -> dict:
        values = {"result_nonempty": bool(result.figures or result.identifiers
                                           or result.data)}
        if result.identifiers and len(result.identifiers) == 1:
            values["unique_entity_key"] = result.identifiers[0].get("id", "")
        if isinstance(result.data, dict):
            for key, value in result.data.items():
                if key != "unique_figure_id" and isinstance(key, str) and isinstance(value, (str, int, bool)):
                    values[key] = value
        if (result.ok and len(result.figures)==1
                and isinstance(result.figures[0].get("id"),str)
                and result.figures[0]["id"].strip()):
            values["unique_figure_id"]=result.figures[0]["id"]
        return values


__all__ = ["ProgramExecutor", "ExecutionResult", "NodeExecution"]
