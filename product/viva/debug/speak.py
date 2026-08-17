"""Read a conversation turn back out of the vault — offline, free, read-only.

Every model exchange in a `viva.speak` session is stored as a `ReadRecorded`
event with `phase="speak"`, carrying the verbatim request (messages and tool
schemas), the verbatim response, and the turn's verdict. This reads them back,
so a turn that refused can be diagnosed without paying to reproduce it — and
so a turn that answered can be shown to have stood on what it said it did.

Usage (from product/, which auto-loads ./.env):

    PYTHONPATH=../core:../merchant:. python3 -m viva.debug.speak        # list turns
    PYTHONPATH=../core:../merchant:. python3 -m viva.debug.speak 3      # one turn
    PYTHONPATH=../core:../merchant:. python3 -m viva.debug.speak 3 --raw

With no argument it lists every recorded turn with its question, verdict, tool
calls, model calls, tokens and cost, under a count of how many sentences were
authored, how many of those the shape check refused, and what it asked to be
changed. Given a turn's number it prints the whole trajectory: each tool call
with its arguments, each result with its size and whether it was an answer or a
refusal, and the reply that ended the turn. `--raw` prints the stored payloads
verbatim instead.

A turn is identified by the doc_id `speak:<session>:<turn>:<exchange>`, and
exchanges are ordered numerically — a turn that spent ten model calls must not
sort its tenth between its first and its second.
"""

from __future__ import annotations

import collections
import json
import os
import pathlib
import sys

HEAD = 400

# The doc_id a speak capture writes: speak:<session>:<turn>:<exchange>.
_PARTS = 4


def cut(text, limit: int = HEAD) -> str:
    """One line of it, with the size of what was left out — never a silent
    truncation, because a payload's bulk is often the finding."""
    text = " ".join(str(text).split())
    return text if len(text) <= limit else f"{text[:limit]} ... [+{len(text) - limit} chars]"


def payload(event) -> dict:
    """The recorded exchange: prompt versions, question, request, response,
    verdict. An unreadable body is empty, never an exception — this tool
    exists to read damaged runs."""
    try:
        body = json.loads(event.body.get("response_text") or "{}")
    except (ValueError, AttributeError):
        return {}
    return body if isinstance(body, dict) else {}


def turns(events) -> dict:
    """Every speak turn in these events, in order, as `{key: [exchanges]}`.

    Keyed by `<session>:<turn>` so one conversation's turns stay together and
    apart from another's. Exchanges sort numerically by their index."""
    found: dict = collections.OrderedDict()
    for event in events:
        if event.event_type != "ReadRecorded":
            continue
        if (event.body.get("phase") or "") != "speak":
            continue
        parts = (event.body.get("doc_id") or "").split(":")
        key = ":".join(parts[1:3]) if len(parts) >= _PARTS else str(
            event.body.get("doc_id") or "")
        found.setdefault(key, []).append(event)

    def index(event) -> int:
        tail = (event.body.get("doc_id") or "").split(":")[-1]
        return int(tail) if tail.isdigit() else 0

    for key in found:
        found[key].sort(key=index)
    return found


def summary(exchanges: list) -> dict:
    """What one turn cost and how it ended."""
    last = payload(exchanges[-1]) if exchanges else {}
    verdict = last.get("verdict") or {}
    return {"question": last.get("question", ""),
            "answered": bool(verdict.get("answered")),
            "refusal": verdict.get("refusal", ""),
            "diagnosis": verdict.get("diagnosis", ""),
            "tool_calls": verdict.get("calls", 0),
            "model_calls": len(exchanges),
            "input_tokens": sum(int(e.body.get("input_tokens") or 0)
                                for e in exchanges),
            "output_tokens": sum(int(e.body.get("output_tokens") or 0)
                                 for e in exchanges),
            "cost_usd": sum(float(e.body.get("cost_usd") or 0)
                            for e in exchanges)}


def shapes(events) -> dict:
    """How often a sentence was authored, how often the authoring was refused,
    and what the refusals asked to be changed.

    Returns ``{"authored": int, "rejected": int, "reasons": {tag: count}}``,
    over every recorded exchange rather than one turn. Counts only exchanges
    that tried to author a shape; a reply refused for anything else is not
    one."""
    authored = rejected = 0
    reasons: dict = collections.Counter()
    for exchanges in turns(events).values():
        for event in exchanges:
            if not payload(event).get("authored_shape"):
                continue
            authored += 1
            if event.body.get("parse_ok"):
                continue
            rejected += 1
            reasons[payload(event).get("defect")
                    or event.body.get("parse_error") or ""] += 1
    return {"authored": authored, "rejected": rejected, "reasons": dict(reasons)}


def _call_lines(message: dict, indent: str) -> list[str]:
    out = []
    for call in message.get("tool_calls") or []:
        fn = (call or {}).get("function") or {}
        out.append(f"{indent}-> {fn.get('name', '?')}"
                   f"({cut(fn.get('arguments') or '', 300)})")
    if message.get("content"):
        out.append(f"{indent}   text: {cut(message['content'], 300)}")
    return out


def _result_lines(content: str, indent: str) -> list[str]:
    size = len(content or "")
    try:
        result = json.loads(content or "{}")
    except ValueError:
        result = None
    if not isinstance(result, dict):
        return [f"{indent}<- [{size} chars] {cut(content)}"]
    tool = result.get("tool", "?")
    if not result.get("ok"):
        return [f"{indent}<- {tool} REFUSED [{size} chars] "
                f"{result.get('refusal', '')}: {cut(result.get('text') or '')}"]
    head = result.get("text") or cut(json.dumps(result.get("data", {})))
    out = [f"{indent}<- {tool} ok [{size} chars] "
           f"grade={result.get('grade', '')} "
           f"figures={len(result.get('figures') or [])} "
           f"records={result.get('records', 0)} :: {cut(head)}"]
    out += [f"{indent}   caveat: {cut(c, 200)}" for c in result.get("caveats") or []]
    return out


def thread_lines(exchanges: list, indent: str = "  ") -> list[str]:
    """The turn's trajectory, rendered.

    The last request carries the whole thread up to it and the last response is
    what ended the turn, so the two together are the complete history — no
    stitching across exchanges, and nothing inferred."""
    last = payload(exchanges[-1]) if exchanges else {}
    messages = (last.get("request") or {}).get("messages") or []
    out = [f"{indent}the thread as the model last saw it — "
           f"{len(messages)} message(s):"]
    for message in messages:
        role = message.get("role", "?")
        content = message.get("content") or ""
        if role == "system":
            out.append(f"{indent}[system] {len(content)} chars (the speak prompt)")
        elif role == "assistant":
            out.append(f"{indent}[viva]")
            out += _call_lines(message, indent + "  ")
        elif role == "tool":
            out += _result_lines(content, indent + "  ")
        else:
            out.append(f"{indent}[{role}] {cut(content)}")
    out.append(f"{indent}[viva, final reply]")
    reply = ((last.get("response") or {}).get("choices") or [{}])[0]
    out += _call_lines((reply or {}).get("message") or {}, indent + "  ")
    carried = sum(len(m.get("content") or "") for m in messages
                  if m.get("role") == "tool")
    out.append(f"{indent}tool results carried in this thread: {carried} chars — "
               "resent in full on every model call.")
    return out


def main() -> None:
    from ..env import load_dotenv
    load_dotenv()
    from ..vault import Vault

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR",
                               os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    raw = "--raw" in sys.argv[1:]

    vault = Vault.open(vault_dir, passphrase)
    events = list(vault.events())
    found = turns(events)
    if not found:
        raise SystemExit("No speak exchanges recorded in this vault.")
    order = list(found)

    if not args:
        counted = shapes(events)
        print(f"{len(order)} recorded turn(s); pass a number to dump one.")
        print(f"shapes: {counted['authored']} authored, "
              f"{counted['rejected']} rejected"
              + ("" if not counted["reasons"] else " — " + ", ".join(
                  f"{reason} x{n}"
                  for reason, n in sorted(counted["reasons"].items()))) + "\n")
        for i, key in enumerate(order, 1):
            s = summary(found[key])
            state = "answered" if s["answered"] else (
                f"REFUSED {s['refusal']}"
                + (f" / {s['diagnosis']}" if s["diagnosis"] else ""))
            print(f"  [{i:>2}] {found[key][0].occurred_at}  {key}")
            print(f"       q: {cut(s['question'], 90)}")
            print(f"       {state} — {s['tool_calls']} tool call(s), "
                  f"{s['model_calls']} model call(s), "
                  f"{s['input_tokens']}/{s['output_tokens']} tokens, "
                  f"${s['cost_usd']:.4f}")
        return

    try:
        key = order[int(args[0]) - 1]
    except (ValueError, IndexError):
        raise SystemExit(f"Pick a turn between 1 and {len(order)}.")

    exchanges = found[key]
    s = summary(exchanges)
    print("=" * 78)
    print(f"turn {args[0]}  ({key})  {exchanges[0].occurred_at}")
    print(f"question: {s['question']}")
    print(f"verdict:  {'answered' if s['answered'] else 'REFUSED ' + s['refusal']}"
          + (f" / {s['diagnosis']}" if s["diagnosis"] else "")
          + f" after {s['tool_calls']} tool call(s)")
    first = payload(exchanges[0])
    print(f"prompts:  {first.get('prompt_versions')}  "
          f"model={first.get('resolved_model')}")
    print("-" * 78)
    for i, event in enumerate(exchanges, 1):
        body = event.body
        print(f"  exchange {i}: {body.get('input_tokens')}/"
              f"{body.get('output_tokens')} tokens, "
              f"${float(body.get('cost_usd') or 0):.4f}"
              + ("" if body.get("parse_ok")
                 else f"  PARSE FAILED: {body.get('parse_error')}"))
    print("-" * 78)

    if raw:
        print(json.dumps([payload(e) for e in exchanges], indent=1))
        return
    for line in thread_lines(exchanges):
        print(line)


if __name__ == "__main__":
    main()
