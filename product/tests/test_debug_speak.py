"""Reading a conversation back out of the vault.

A refused turn is the one we most need to explain, and it is the one nobody
can afford to reproduce — each replay is real money to a hosted model. So the
capture in the vault is the only record, and this reader is what makes it
legible. These tests hold it to three things: the turns come back grouped and
in the order they happened, what a turn cost is reported rather than guessed,
and the thread's shape survives — a refusal is shown as a refusal, and the
bulk of the tool payloads is stated rather than quietly cut away.

The ordering test is the load-bearing one. Exchange indices are text in a
doc_id, and a turn that spends ten model calls would sort its tenth between
its first and its second if they were compared as text — which would print a
trajectory that never happened.
"""

import json

from viva.debug.speak import summary, thread_lines, turns
from viva.ledger.events import read_recorded


def _exchange(session: str, turn: int, index: int, *, question: str = "q",
              request: dict | None = None, response: dict | None = None,
              verdict: dict | None = None, tokens: tuple = (10, 2),
              cost: float = 0.01):
    return read_recorded(
        doc_id=f"speak:{session}:{turn}:{index}",
        model="a-model", prompt_version="speak-v4", input_mode="native-tools",
        response_text=json.dumps({
            "question": question,
            "request": request or {"messages": []},
            "response": response or {},
            "verdict": verdict or {"answered": False, "refusal": "",
                                   "calls": 0}}),
        cost_usd=cost, input_tokens=tokens[0], output_tokens=tokens[1],
        parse_ok=True, parse_error=None, occurred_at="2026-08-04",
        phase="speak")


def test_only_speak_captures_are_read():
    """A document read is a ReadRecorded too. Reading one as a conversation
    would report a statement's extraction as a turn nobody took."""
    events = [_exchange("s1", 1, 1),
              read_recorded(doc_id="abc123", model="m", prompt_version="p",
                            input_mode="pdf", response_text="{}", cost_usd=0.0,
                            input_tokens=0, output_tokens=0, parse_ok=True,
                            parse_error=None, occurred_at="2026-08-04")]
    found = turns(events)
    assert list(found) == ["s1:1"]


def test_turns_group_by_session_and_turn():
    events = [_exchange("s1", 1, 1), _exchange("s1", 2, 1),
              _exchange("s2", 1, 1)]
    assert list(turns(events)) == ["s1:1", "s1:2", "s2:1"]


def test_exchanges_order_numerically_not_lexically():
    events = [_exchange("s1", 1, i) for i in (1, 10, 2, 9)]
    order = [e.body["doc_id"].split(":")[-1] for e in turns(events)["s1:1"]]
    assert order == ["1", "2", "9", "10"]


def test_summary_reports_the_refusal_and_what_it_cost():
    events = [_exchange("s1", 1, 1, question="what is my net worth",
                        tokens=(100, 20), cost=0.02),
              _exchange("s1", 1, 2, question="what is my net worth",
                        tokens=(900, 30), cost=0.06,
                        verdict={"answered": False,
                                 "refusal": "call_budget_exhausted",
                                 "calls": 8})]
    s = summary(turns(events)["s1:1"])
    assert s["question"] == "what is my net worth"
    assert s["answered"] is False
    assert s["refusal"] == "call_budget_exhausted"
    assert s["tool_calls"] == 8            # tool calls, from the verdict
    assert s["model_calls"] == 2           # model calls, counted here
    assert (s["input_tokens"], s["output_tokens"]) == (1000, 50)
    assert abs(s["cost_usd"] - 0.08) < 1e-9


def test_thread_shows_the_calls_the_results_and_the_carried_bulk():
    result = json.dumps({"tool": "query_ledger", "ok": False,
                         "reason": "unknown_merchant",
                         "text": "No counterparty 'costco' is on file."})
    request = {"messages": [
        {"role": "system", "content": "you are viva"},
        {"role": "user", "content": "how much did i spend on costco"},
        {"role": "assistant", "tool_calls": [
            {"function": {"name": "query_ledger",
                          "arguments": '{"entity": "transactions"}'}}]},
        {"role": "tool", "content": result},
    ]}
    response = {"choices": [{"message": {"tool_calls": [
        {"function": {"name": "deliver_answer", "arguments": "{}"}}]}}]}
    lines = thread_lines(turns([_exchange("s1", 1, 1, request=request,
                                          response=response)])["s1:1"])
    text = "\n".join(lines)
    assert "how much did i spend on costco" in text
    assert "-> query_ledger" in text
    assert "REFUSED" in text and "unknown_merchant" in text
    assert "-> deliver_answer" in text                     # the reply that ended it
    assert f"{len(result)} chars" in text                  # what the payload weighs
    assert "the speak prompt" in text                      # system prompt, not dumped


def test_a_long_payload_says_what_it_hid():
    """Truncation is fine; silent truncation is not — the size of what was cut
    is often the whole finding."""
    long_text = "x" * 5000
    request = {"messages": [{"role": "user", "content": long_text}]}
    text = "\n".join(thread_lines(
        turns([_exchange("s1", 1, 1, request=request)])["s1:1"]))
    assert "..." in text and "+4600 chars" in text
