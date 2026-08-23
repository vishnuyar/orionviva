"""Viva speaks: a live model plans read-tool calls and composes the answer.

The runner and its citation gate already hold the law — every figure in an
answer must be grounded in this run's tool results. This module supplies the
planners that put a real model behind that contract, a session that carries a
conversation across turns, and the capture that records every exchange in the
vault.

Two planners, one contract:

- ``NativePlanner`` speaks the chat-completions tool-calling protocol through
  an adapter's ``converse`` — the primary path for every OpenAI-compatible
  endpoint, hosted or local.
- ``TextPlanner`` teaches the same steps as a fenced JSON block over a plain
  completion — the degradation path for any model the ``extract`` contract can
  reach.

Both present two schemas beside the registry's verbs, and which of them is on
the table is decided by the runner rather than by either planner:
``commit_shape``, through which a turn's sentence is authored before anything
is read, and ``deliver_answer``, through which each of that sentence's holes is
bound to something the reads established. Neither is registered — neither
executes anything; one opens a turn and one ends it. A malformed reply gets
exactly one correction, naming the defect and the one change that answers it,
then the turn refuses with a machine tag. A transport failure refuses as
``model_unreachable``. Nothing raises to the person.

One shape of last word exists besides an ordinary answer. When the call budget
runs out, the runner asks once more with only the terminator on the table, so a
turn already holding grounded figures can still deliver what its shape asked
for. A refusal is not the model's to write: it is a reviewed sentence in the
persona pack chosen by the machine tag, so no planner is asked to compose one
and a refused turn spends nothing.

A session keeps prior turns as context so follow-ups resolve ("it", "that
account"), but the gate's grounding is per-turn: any figure the model wants to
repeat must be re-fetched by a tool in the current turn.

Every model exchange is appended to the ledger as a ``ReadRecorded`` event,
``phase="speak"``, carrying the verbatim request and response, the prompt
versions in force, the pinned and endpoint-reported model, tokens and cost.
"""

from __future__ import annotations

from dataclasses import replace

from .planners import *
from .planners import __all__ as _PLANNER_EXPORTS
from .session import Session, Turn
from .tools.runner import DEFAULT_MAX_CALLS, RunResult

def speak_spec():
    """The pinned model the conversation speaks through, or None when no model
    is configured.

    Configured per field: ``VIVA_SPEAK_<FIELD>`` if set, else the matching
    ``VIVA_MODEL_<FIELD>``, so the voice and the document reader can be
    different models. Pointing ``VIVA_SPEAK_BASE_URL`` at a local server
    (Ollama, LM Studio) with ``VIVA_SPEAK_KEY_ENV=none`` keeps the whole
    conversation on the machine."""
    import os

    def cfg(fld, default=None):
        return (os.environ.get(f"VIVA_SPEAK_{fld}")
                or os.environ.get(f"VIVA_MODEL_{fld}" if fld != "MODEL"
                                  else "VIVA_MODEL")
                or default)

    model = cfg("MODEL")
    if not model:
        return None
    from vivacore.models import ModelSpec
    key_env = cfg("KEY_ENV", "OPENROUTER_API_KEY")
    return ModelSpec(
        name="viva-speak", adapter=cfg("ADAPTER", "openai-compatible"),
        model=model, base_url=cfg("BASE_URL"),
        api_key_env=None if (key_env or "").lower() in ("", "none") else key_env)


def planner_factory(spec):
    """Planner constructor for one spec: native tool-calling where the adapter
    speaks it, the text protocol otherwise or when ``VIVA_SPEAK_PROTOCOL=text``
    forces it — the per-model reversibility the modality contract promised."""
    import os

    from vivacore.models import adapter_for

    forced_text = os.environ.get("VIVA_SPEAK_PROTOCOL", "").strip() == "text"
    # A truncated reply is a malformed step to correct, never a fragment to
    # stitch, so continuation stays off for both modalities.
    adapter = adapter_for(replace(spec, max_continuations=0))
    native = hasattr(adapter, "converse") and not forced_text

    def make(prior_turns):
        if native:
            return NativePlanner(adapter, prior_turns)
        return TextPlanner(adapter, prior_turns)

    return make


def max_calls_from_env() -> int:
    import os

    raw = os.environ.get("VIVA_SPEAK_MAX_CALLS", "").strip()
    return int(raw) if raw.isdigit() and int(raw) > 0 else DEFAULT_MAX_CALLS


def _shown(result: RunResult) -> dict:
    """Figure id -> the words that figure was written as in the sentence.

    The footer does not decide a second time how a figure becomes words. It
    shows what the hole this figure filled was written as, so the number under
    the sentence is the number in the sentence — its hedge, its currency, its
    conventions and its kind all the same, because they are the same string.

    One figure can fill more than one hole: an amount in one clause and, in
    another, how well that same amount is stood behind. Every distinct form it
    was written as is kept, joined in the order the sentence wrote them."""
    forms: dict = {}
    for name, reference in result.bindings.items():
        if "figure" not in reference:
            continue
        written = result.written.get(name, "")
        kept = forms.setdefault(str(reference["figure"]), [])
        if written and written not in kept:
            kept.append(written)
    return {fid: ", ".join(kept) for fid, kept in forms.items()}


def _print_turn(turn: Turn) -> None:
    result = turn.result
    print()
    if result.answered:
        print(f"Viva: {result.text}")
        if result.grade:
            print(f"  grade: {result.grade}")
        elif result.figures:
            print("  grade: none — " + ", ".join(
                sorted({f.get("kind", "") for f in result.figures})))
        shown = _shown(result)
        for figure in result.figures:
            ids = ", ".join(map(str, figure.get("record_ids", [])))
            grade = figure.get("grade", "") or figure.get("kind", "")
            parts = [str(figure.get("id"))]
            if shown.get(str(figure.get("id"))):
                parts.append(shown[str(figure.get("id"))])
            if grade:
                parts.append(f"({grade})")
            print("  " + " ".join(parts)
                  + f"  {figure.get('what', '')}  <- {ids}")
        for gap in result.gaps:
            print(f"  gap: {gap['name']} ({gap['type']}) — nothing bound")
    else:
        print(f"Viva: {result.text or 'I have no answer.'}")
        print(f"  refused: {result.refusal}")
    tokens_in, tokens_out = turn.tokens
    print(f"  [{result.calls} tool call(s), {len(turn.exchanges)} model "
          f"call(s), {tokens_in}/{tokens_out} tokens, "
          f"${turn.cost_usd:.4f}]")


def main() -> None:
    import os
    import pathlib
    import sys

    from .env import load_dotenv
    from .logs import configure as configure_logging

    load_dotenv()
    configure_logging()

    spec = speak_spec()
    if spec is None:
        raise SystemExit("No model configured. Set VIVA_SPEAK_MODEL or "
                         "VIVA_MODEL (with ADAPTER / BASE_URL / KEY_ENV as "
                         "needed), or put them in ./.env.")

    passphrase = os.environ.get("VIVA_PASSPHRASE")
    if not passphrase:
        raise SystemExit("Set VIVA_PASSPHRASE (it is never stored).")
    vault_dir = os.environ.get("VIVA_VAULT_DIR",
                               os.path.expanduser("~/.viva-vault"))
    if not pathlib.Path(vault_dir).exists():
        raise SystemExit(f"No vault at {vault_dir}.")

    from .tools import default_registry
    from .vault import Vault

    from .env import locale_from_env

    locale = locale_from_env()
    vault = Vault.open(vault_dir, passphrase)
    registry = default_registry(vault.ledger.projection(), locale)
    session = Session(registry, planner_factory(spec), ledger=vault.ledger,
                      model=spec.model, max_calls=max_calls_from_env(),
                      locale=locale)

    questions = list(sys.argv[1:])
    if questions:
        for question in questions:
            print(f"you: {question}")
            _print_turn(session.ask(question))
        return

    print("Ask about your money; a blank line ends the conversation.")
    while True:
        try:
            question = input("you: ").strip()
        except EOFError:
            break
        if not question:
            break
        _print_turn(session.ask(question))


if __name__ == "__main__":
    main()
