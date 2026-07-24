"""Debug a single real document read, end to end — prints the RAW model output.

This is the tool for exactly the "I uploaded it but see no data" moment: it shows
what the model classified the document as, its raw output, whether the structured
parse succeeded (and if not, why), and whether it reconciles — i.e. whether the
statement would POST, HOLD for review, or PARK.

Usage (from product/, with your model env set — it auto-loads ./.env):

    PYTHONPATH=../core:. python3 -m viva.debug_read /path/to/statement.pdf [locale] [currency]

Nothing is written to a vault; this only reads and reports.
"""

from __future__ import annotations

import os
import pathlib
import sys

from .env import load_dotenv
from .logs import configure as configure_logging


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python -m viva.debug_read <pdf> [locale] [currency]")
    load_dotenv()
    configure_logging()

    from vivacore.models import ModelSpec, adapter_for
    from vivacore.verify.arithmetic import check_balance_identity
    from .ingest import from_model_json
    from .ingest.diagnose import diagnose
    from .ingest.registry import extraction_prompt_for
    from .ingest.reader import _render_and_read_text, _with_embedded, classify

    pdf_path = sys.argv[1]
    locale = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("VIVA_LOCALE", "en-US")
    currency = sys.argv[3] if len(sys.argv) > 3 else os.environ.get("VIVA_CURRENCY", "USD")

    if not os.environ.get("VIVA_MODEL"):
        raise SystemExit("No model configured. Set VIVA_MODEL_ADAPTER / VIVA_MODEL / "
                         "VIVA_MODEL_KEY_ENV (and the key), or put them in ./.env.")

    spec = ModelSpec(
        name="debug", adapter=os.environ["VIVA_MODEL_ADAPTER"],
        model=os.environ["VIVA_MODEL"],
        base_url=os.environ.get("VIVA_MODEL_BASE_URL"),
        api_key_env=os.environ.get("VIVA_MODEL_KEY_ENV", "OPENROUTER_API_KEY"),
        json_mode=True)

    data = pathlib.Path(pdf_path).read_bytes()
    pages, text = _render_and_read_text(data)
    print(f"[render] {len(pages)} pages, {len(text)} chars of embedded text  ({locale}/{currency})")

    adapter = adapter_for(spec)

    # Phase 1: classify (cheap — first page + embedded text).
    doc_type, conf, cphase = classify(adapter, pages, text)
    print(f"[classify] {doc_type!r} (conf={conf:.2f}, {cphase.model}, cost=${cphase.cost_usd:.4f})")
    composed = extraction_prompt_for(doc_type)
    if composed is None:
        print(f"        -> no projector for {doc_type!r}; this document would PARK "
              "(captured, not posted) until a profile for its type exists.")
        return

    # Phase 2: extract with the type's own composed prompt.
    prompt_text, prompt_version = composed
    print(f"[extract] prompt {prompt_version}")
    res = adapter.extract(pages, _with_embedded(prompt_text, text))
    print(f"[model] {res.resolved_model}  cost=${res.cost_usd:.4f}")
    print("=" * 30 + " RAW MODEL OUTPUT " + "=" * 30)
    print(res.text)
    print("=" * 78)

    facts, err = from_model_json(res.text, "debug", locale, currency)
    if err:
        print(f"[parse] FAILED: {err}")
        print("        -> would PARK (captured, not posted). The raw output above "
              "shows what the model returned; the fix is usually a prompt/schema nudge.")
        return

    facts.doc_type = doc_type            # classification is authoritative (extract prompt doesn't re-ask)
    print(f"[parse] ok — doc_type={facts.doc_type!r}  account={facts.account_ref!r}  {facts.currency}")
    print(f"        opening {facts.opening_amount} ({facts.opening_date}) -> "
          f"closing {facts.closing_amount} ({facts.closing_date}); {len(facts.transactions)} transactions")
    r = check_balance_identity(facts.opening_amount,
                               [t.amount for t in facts.transactions],
                               facts.closing_amount)
    if r.passed:
        print(f"[reconcile] PASS -> would POST (corroborated). {r.explain()}")
    else:
        print(f"[reconcile] FAIL -> would HOLD for review. {r.explain()}")
        d = diagnose(facts)
        print(f"[diagnose] {d.status}/{d.kind}: {d.message}")


if __name__ == "__main__":
    main()
