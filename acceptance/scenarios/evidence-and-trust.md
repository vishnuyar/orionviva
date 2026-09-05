# Evidence and trust

## TRUST-001 — Net-worth evidence is actionable

**Actions:** From a visible net-worth figure, use its evidence action.

**Pass:** The action remains available after the page settles and opens evidence
that explains the figure's components and scope.

## TRUST-002 — A transaction traces to its source

**Actions:** Choose a transaction and follow its available evidence.

**Pass:** The destination identifies the supporting source without exposing an
unrelated document or losing the active vault.

## TRUST-003 — Evidence destination survives navigation

**Actions:** Open evidence, return to the source surface, navigate elsewhere,
and repeat the evidence action.

**Pass:** The destination remains actionable and context-correct. It does not
become disabled because vault state was silently lost.

## TRUST-004 — Uncertainty is visible before reliance

**Actions:** Find a figure or classification that the test inputs make
ambiguous.

**Pass:** Confidence, review need, or limitation appears where the user decides
whether to rely on it, not only in a hidden diagnostic view.

## TRUST-005 — Correction becomes durable knowledge

**Actions:** Correct an eligible synthetic classification through Review, then
revisit the affected transaction and restart the application.

**Pass:** The correction is reflected consistently and survives restart without
changing unrelated records.

## TRUST-006 — Outbound model activity is inspectable

**Prerequisite:** A model provider is explicitly configured for a synthetic run.

**Actions:** Trigger one document-reading or question request, then open the
Trust or outbound-activity view.

**Pass:** The activity is visible with enough context to understand why it
happened. No model call occurs merely from navigating local surfaces.

## TRUST-007 — Offline/local behavior is honestly bounded

**Actions:** With model access unavailable, use local financial surfaces and
attempt a feature that requires a model.

**Pass:** Local deterministic information remains usable. The model-dependent
feature explains its limitation without pretending to have completed or
discarding vault state.

