"""Everything this vault has ever sent, composed from the log that recorded it.

The promise inventory already makes a public promise: nothing leaves your
machine silently, only user-initiated model calls and anonymous anchor hashes,
and *"the complete outbound record is always visible in the product"*. The
invariant behind it has so far been kept by there being nothing to show rather
than by showing it. This is the showing.

**The absences are in the read model.** What this record does not cover, and
that nothing outside this machine holds a hash of any of it, are sentences the
read carries — not a paragraph a screen composes underneath a list. A screen
that writes its own caveats writes them out of date the day the capability
lands, and nothing goes red when it does.

**A vault that has sent nothing says so.** An empty list and a panel that
failed to load are the same picture, so the emptiness is stated rather than
rendered.

**A phase this build has no sentence for is not described by the nearest one.**
The log records which pass a model call belonged to. Each has a reviewed line
saying what was actually sent on it; a call recorded under a name added later
says that it exists and that what it sent is not described here, which is the
honest rendering of a word this build does not know.

A pure fold over an event stream. It opens nothing, reads no clock, calls
nothing, and knows nothing about how the payload travels.
"""

from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from .. import render
from ..persona import moment
from .models import PanelState

# The event a model call is recorded as. There is exactly one, which is what
# makes a complete list of them a complete list of what has left.
READ_RECORDED = "ReadRecorded"

# Each pass a model call can belong to, against the sentence that says what was
# actually sent on it. A phase outside this table is real and is reported as
# unnamed rather than folded into the nearest row.
PHASES: dict[str, str] = {
    "classify": "outbound_phase_classify",
    "extract": "outbound_phase_extract",
    "interpret": "outbound_phase_interpret",
    "speak": "outbound_phase_speak",
}
UNNAMED = "outbound_phase_unnamed"

# The currency every recorded price is in. It is the field's own name — the log
# records `cost_usd` — and it is stated here rather than read from a person's
# configured currency, because what a provider charged is not converted by
# anything in this product and a figure relabelled is a figure invented.
COST_CURRENCY = "USD"


def outbound(events: Iterable[Any], locale: str = "") -> dict[str, Any]:
    """The complete outbound record, ready to render.

    ``events`` is the vault's own event stream. Only the model-call events are
    read; everything else is passed over, so this stays a fold rather than a
    projection with a second opinion about what a vault holds."""
    calls = [event for event in events if getattr(event, "event_type", "") == READ_RECORDED]
    if not calls:
        return _nothing_left()

    phases = Counter(_phase(call) for call in calls)
    models = Counter(_model(call) for call in calls if _model(call))
    reported_models = Counter(_reported_model(call) for call in calls
                              if _reported_model(call))
    legacy_models = Counter(_legacy_model(call) for call in calls
                            if _legacy_model(call))
    days = sorted(_day(call) for call in calls if _day(call))
    tokens = _tokens(calls)
    return {
        "state": PanelState.READY.value,
        "sentence": moment("outbound_some"),
        "call_count": len(calls),
        # One line per pass, in the order the passes happen rather than by how
        # many of each there are: a person reading this is following what the
        # product did, not ranking it.
        "phases": [
            {"id": name, "count": phases[name],
             "sentence": moment(PHASES[name], count=render.count(phases[name]))}
            for name in PHASES if phases[name]
        ] + ([
            {"id": "unnamed", "count": _unnamed(phases),
             "sentence": moment(UNNAMED, count=render.count(_unnamed(phases)))}
        ] if _unnamed(phases) else []),
        "models": [
            {"name": name, "count": count} for name, count in sorted(models.items())
        ],
        **({"reported_models": [
            {"name": name, "count": count}
            for name, count in sorted(reported_models.items())
        ]} if reported_models else {}),
        **({"legacy_models": [
            {"name": name, "count": count}
            for name, count in sorted(legacy_models.items())
        ]} if legacy_models else {}),
        **({"tokens": tokens} if tokens is not None else {}),
        "model_sentence": moment(
            "outbound_models",
            count=render.count(len(set(models) | set(reported_models)
                                   | set(legacy_models)))),
        "span": ({
            "first": days[0], "last": days[-1],
            "sentence": moment("outbound_window",
                               first=render.date(days[0]),
                               last=render.date(days[-1])),
        } if days else None),
        "cost": _cost(calls, locale),
        # The absences, carried by the read. Neither is a caveat a screen
        # writes: the first says what a complete list of model calls is a
        # complete list of, and the second says plainly that no third party
        # could confirm any of it, because external anchoring is not built.
        "absences": [
            {"id": "scope", "sentence": moment("outbound_scope")},
            {"id": "anchoring", "sentence": moment("outbound_no_anchor")},
        ],
    }


def _nothing_left() -> dict[str, Any]:
    """The record of a vault that has never called a model.

    It is `ready` rather than `absent`: the panel has something true to say,
    and saying it is the whole point. An absent panel would render as a feature
    that has not landed, which is the opposite of the fact."""
    return {
        "state": PanelState.READY.value,
        "sentence": moment("outbound_none"),
        "call_count": 0,
        "phases": [],
        "models": [],
        "legacy_models": [],
        "model_sentence": "",
        "span": None,
        "cost": None,
        "absences": [
            {"id": "scope", "sentence": moment("outbound_scope")},
            {"id": "anchoring", "sentence": moment("outbound_no_anchor")},
        ],
    }


def _unnamed(phases: Counter) -> int:
    return sum(count for name, count in phases.items() if name not in PHASES)


def _phase(call: Any) -> str:
    body = getattr(call, "body", {}) or {}
    phase = body.get("phase", "extract")
    return phase if isinstance(phase, str) and phase.strip() else "extract"


def _model(call: Any) -> str:
    body = getattr(call, "body", {}) or {}
    if body.get("model_role") != "configured_route":
        return ""
    model = body.get("model", "")
    return model.strip() if isinstance(model, str) else ""


def _legacy_model(call: Any) -> str:
    """A model value whose configured/provider role is not recorded."""
    body = getattr(call, "body", {}) or {}
    if body.get("model_role") == "configured_route":
        return ""
    model = body.get("model", "")
    return model.strip() if isinstance(model, str) else ""


def _reported_model(call: Any) -> str:
    body = getattr(call, "body", {}) or {}
    model = body.get("resolved_model", "")
    return model.strip() if isinstance(model, str) else ""


def _day(call: Any) -> str:
    """The day a call was recorded on, as the log wrote it.

    Only the date part travels. A time of day says what a person was doing at
    four in the morning, which is not a fact this record exists to publish."""
    occurred = getattr(call, "occurred_at", "")
    return occurred[:10] if isinstance(occurred, str) and len(occurred) >= 10 else ""


def _tokens(calls: list[Any]) -> dict[str, int] | None:
    """Provider-reported token totals, only where at least one was measured."""
    inputs = outputs = measured = 0
    for call in calls:
        body = getattr(call, "body", {}) or {}
        # The marker makes zero measurable. Positive unmarked counters also
        # represent usage; unmarked zero remains absent.
        explicit = body.get("usage_reported") is True
        found = False
        for field, target in (("input_tokens", "input"),
                              ("output_tokens", "output")):
            value = body.get(field)
            if isinstance(value, int) and not isinstance(value, bool) \
                    and value >= 0 and (explicit or value > 0):
                if target == "input":
                    inputs += value
                else:
                    outputs += value
                found = True
        measured += int(found)
    if not measured:
        return None
    return {"input": inputs, "output": outputs, "total": inputs + outputs,
            "measured_calls": measured}


def _cost(calls: list[Any], locale: str) -> dict[str, Any] | None:
    """What every recorded call cost, added up.

    The log records a price as a float, because that is what a provider's own
    reply carries. It is summed through `Decimal` over the text of each value,
    so the total is the sum of the digits recorded rather than the sum of the
    binary approximations of them — a figure a person may be reading against a
    bill.

    A vault whose calls recorded no price at all gets no total, rather than a
    zero: nothing was measured, and zero is a measurement."""
    total = Decimal("0")
    measured = 0
    for call in calls:
        body = getattr(call, "body", {}) or {}
        value = body.get("cost_usd")
        if value is None or isinstance(value, bool):
            continue
        try:
            total += Decimal(str(value))
        except (InvalidOperation, ValueError):
            continue
        measured += 1
    if not measured:
        return None
    amount = render.money(total, COST_CURRENCY, locale=locale)
    return {
        "exact_value": str(total),
        "currency": COST_CURRENCY,
        "display": str(amount),
        "measured_calls": measured,
        "sentence": moment("outbound_cost", amount=amount),
    }
