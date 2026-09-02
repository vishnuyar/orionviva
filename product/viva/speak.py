"""Viva speaks through one compact semantic request per turn.

The model sees data-blind question context and a reviewed semantic catalog,
never live vault values or executable contracts. Code lowers the selected
meaning and typed parameters to a complete AnswerProgram, validates it before
any read, then uses the existing deterministic execution and delivery path.
"""

from __future__ import annotations

from dataclasses import replace
import json
import pathlib

from .answer_program import AnswerProgramCompiler, AnswerResourcePolicy
from .session import Session, Turn
from .tools.runner import RunResult

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


def compiler_factory(spec, *, purpose="runtime", profile=None, report=None,
                     locale=""):
    """Build the one-shot compiler for an admitted runtime or measured run.

    Admission and an explicitly marked local Witness are allowed to measure an
    unpublished model. Ordinary runtime use must load the exact profile that
    was admitted for this build.
    """
    import os

    from vivacore.models import adapter_for

    adapter = adapter_for(replace(spec, max_continuations=0))
    forced_text = os.environ.get("VIVA_SPEAK_PROTOCOL", "").strip() == "text"
    modality = ("native-structured"
                if hasattr(adapter, "converse") and not forced_text
                else "text-json")
    endpoint = str(getattr(spec, "base_url", "") or "provider-default")
    configured = {
        "provider": str(getattr(spec, "adapter", "") or ""),
        "requested_model": str(getattr(spec, "model", "") or ""),
        "endpoint": endpoint,
        "modality": modality,
    }
    if purpose not in ("runtime", "admission", "witness"):
        raise ValueError("unknown compiler purpose")
    witness_marker = os.environ.get("VIVA_WITNESS", "").strip() == "1"
    if purpose == "witness" and not witness_marker:
        raise ValueError("Witness compilation needs VIVA_WITNESS=1")
    if purpose == "runtime" and profile is None:
        bundle_path = os.environ.get("VIVA_ADMISSION_PROFILE", "").strip()
        if not bundle_path:
            raise ValueError(
                "runtime answering needs VIVA_ADMISSION_PROFILE; admission and "
                "Witness runs must opt into their explicit purpose")
        from .answer_program import (AdmissionProfile, AdmissionThresholds,
                                     admission_report_digest)
        payload = json.loads(pathlib.Path(bundle_path).read_text(encoding="utf-8"))
        raw_profile = dict(payload.get("profile") or payload)
        raw_report = payload.get("admission_report")
        if (not isinstance(raw_report, dict)
                or raw_profile.get("admission_report_digest")
                != admission_report_digest(raw_report)):
            raise ValueError("runtime admission bundle is not tied to its report")
        report = raw_report
        raw_profile["thresholds"] = AdmissionThresholds(
            **dict(raw_profile["thresholds"]))
        profile = AdmissionProfile(**raw_profile)
    if purpose == "runtime":
        from .answer_program import (admission_report_digest,
                                     validate_admission_report)
        if (report is None
                or profile.admission_report_digest
                != admission_report_digest(report)):
            raise ValueError("runtime admission profile needs its measured report")
        report_failures = validate_admission_report(report, profile)
        if report_failures:
            raise ValueError("runtime admission report failed: "
                             + ", ".join(report_failures))
        for field, value in configured.items():
            if getattr(profile, field) != value:
                raise ValueError(f"runtime model differs from admitted {field}")
        if not locale:
            from .env import locale_from_env
            locale = locale_from_env()
        locale_family = locale.replace("_", "-").split("-", 1)[0].casefold()
        if profile.locale_family != locale_family:
            raise ValueError("runtime locale differs from admitted locale_family")

    def make(validator, manifest, policy):
        if purpose == "runtime":
            from .answer_program import check_profile, resource_policy_digest
            checked = check_profile(profile, manifest, report, policy)
            if not checked.passed:
                raise ValueError("admission profile differs from this build: "
                                 + ", ".join(checked.failures))
            if profile.resource_policy_digest != resource_policy_digest(policy):
                raise ValueError("runtime resource policy differs from admission")
        return AnswerProgramCompiler(adapter, validator, manifest, policy,
                                     modality=modality,
                                     expected_resolved_model=(
                                         profile.resolved_model
                                         if purpose == "runtime"
                                         else ""))

    make.admission_identity = configured
    return make


def resource_policy_from_env() -> AnswerResourcePolicy:
    """Named local-execution limits; model attempts remain fixed at two."""
    import os

    defaults = AnswerResourcePolicy()

    def positive(name, default):
        raw = os.environ.get(name, "").strip()
        return int(raw) if raw.isdigit() and int(raw) > 0 else default

    return AnswerResourcePolicy(
        max_model_attempts=2,
        max_required_nodes=positive("VIVA_ANSWER_MAX_REQUIRED_NODES",
                                    defaults.max_required_nodes),
        max_supporting_nodes=positive("VIVA_ANSWER_MAX_SUPPORTING_NODES",
                                      defaults.max_supporting_nodes),
        max_optional_nodes=positive("VIVA_ANSWER_MAX_OPTIONAL_NODES",
                                    defaults.max_optional_nodes),
        max_dependency_depth=positive("VIVA_ANSWER_MAX_DEPENDENCY_DEPTH",
                                      defaults.max_dependency_depth),
        max_evidence_bytes=positive("VIVA_ANSWER_MAX_EVIDENCE_BYTES",
                                    defaults.max_evidence_bytes),
        max_execution_ms=positive("VIVA_ANSWER_MAX_EXECUTION_MS",
                                  defaults.max_execution_ms),
        max_figures=positive("VIVA_ANSWER_MAX_FIGURES", defaults.max_figures))


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
    session = Session(registry, compiler_factory(spec), ledger=vault.ledger,
                      model=spec.model, resource_policy=resource_policy_from_env(),
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
