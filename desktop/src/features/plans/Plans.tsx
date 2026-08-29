import { useEffect, useState, type FormEvent } from "react";
import { PanelStateView } from "../../components/PanelStateView";
import type { ActionResult, EvidenceLink, FeatureResult, GoalPlanView, PlanDraftResult, PlanPayload, PlansData } from "../../surface/types";

type PlanControls = {
  draft: (payload: PlanPayload) => Promise<PlanDraftResult>;
  propose: (payload: PlanPayload) => Promise<ActionResult>;
  confirm: (proposalId: string) => Promise<ActionResult>;
  decline: (proposalId: string) => Promise<ActionResult>;
};
type Props = { result: FeatureResult<PlansData>; controls: PlanControls | null; initialDraft?: PlanDraftResult | null; receipt?: ActionResult | null; onOpenEvidence: (link: EvidenceLink) => void };

function outcomeMessage(result: ActionResult | null): string {
  if (!result) return "";
  if (result.state === "settled") return result.outcome.message;
  if (result.state === "unserved") return "This plan action is not available in this build.";
  if (result.state === "unanswered") return "The vault did not answer. Nothing on this screen assumes the action happened.";
  return "The reply could not be read. Read the vault again before trying another plan action.";
}

function ChangeTerms({ goal, controls }: { goal: GoalPlanView; controls: PlanControls }) {
  const waitingId = `plan-change-waiting-${goal.id}`;
  const [title, setTitle] = useState(goal.title);
  const [target, setTarget] = useState(goal.targetAmount);
  const [date, setDate] = useState(goal.targetDate);
  const [monthly, setMonthly] = useState(goal.monthlyContribution);
  const [day, setDay] = useState<number | "">(goal.contributionDay ?? "");
  const [draft, setDraft] = useState<PlanDraftResult | null>(null);
  const [busy, setBusy] = useState(false);
  const payload = (): PlanPayload => ({ verb: "change_terms", goal_id: goal.id, title, currency: goal.currency, target_amount: target, ...(date ? { target_date: date } : {}), ...(monthly ? { monthly_contribution: monthly } : {}), ...(day !== "" ? { contribution_day: day } : {}) });
  async function calculate(event: FormEvent) { event.preventDefault(); if (busy) return; setBusy(true); try { setDraft(await controls.draft(payload())); } finally { setBusy(false); } }
  async function hold() { if (busy || draft?.state !== "settled" || draft.kind !== "ready" || !draft.draft) return; setBusy(true); try { await controls.propose({ verb: draft.draft.verb, ...draft.draft.payload }); setDraft(null); } finally { setBusy(false); } }
  const ready = draft?.state === "settled" && draft.kind === "ready" ? draft.draft : null;
  return <form className="plans-term-form" aria-label={`Change terms for ${goal.title}`} onSubmit={calculate}><strong>Change terms</strong><label>Plan name<input required value={title} onChange={(event) => setTitle(event.target.value)} /></label><label>Target amount<input required inputMode="decimal" value={target} onChange={(event) => setTarget(event.target.value)} /></label><label>Target date<input type="date" value={date} onChange={(event) => setDate(event.target.value)} /></label><label>Monthly contribution<input inputMode="decimal" value={monthly} onChange={(event) => setMonthly(event.target.value)} /></label><label>Contribution day<input type="number" min="1" max="28" value={day} onChange={(event) => setDay(event.target.value === "" ? "" : event.target.valueAsNumber)} /></label><button className="secondary-button" aria-disabled={busy} aria-describedby={busy ? waitingId : undefined}>Calculate changed terms</button>{draft?.state === "settled" ? <span role="status">{draft.message}</span> : null}{ready ? <div className="plans-draft"><span>Target: {String(ready.payload.target_amount)} {String(ready.payload.currency)}</span><span>Required monthly: {ready.calculated.required_monthly || "Not available"}</span><span>Projected completion: {ready.calculated.projected_completion_date || "Not scheduled"}</span><button className="secondary-button" type="button" onClick={() => void hold()} aria-disabled={busy} aria-describedby={busy ? waitingId : undefined}>Hold changed terms</button></div> : null}{busy ? <span id={waitingId} role="status">Waiting for the vault…</span> : null}</form>;
}

function ProposalCard({ proposal, controls }: { proposal: PlansData["proposals"][number]; controls: PlanControls | null }) {
  const [busy, setBusy] = useState(false);
  const waitingId = `plan-proposal-waiting-${proposal.id}`;
  async function act(run: () => Promise<ActionResult>) { if (busy) return; setBusy(true); try { await run(); } finally { setBusy(false); } }
  const labels: Record<string, string> = { plan_name: "Plan", account_name: "Account", target_amount: "Target", amount: "Amount", target_date: "Target date", monthly_contribution: "Monthly contribution", contribution_day: "Contribution day" };
  return <section className="feature-panel plans-proposal" aria-labelledby={`proposal-${proposal.id}`}><span className="eyebrow">Waiting for confirmation</span><h2 id={`proposal-${proposal.id}`} tabIndex={-1}>{proposal.summary}</h2><p>{proposal.consequence}</p><p>{proposal.noMoneyMoved}</p><dl className="plans-exact">{Object.entries(proposal.display).map(([key, value]) => <div key={key}><dt>{labels[key] ?? key}</dt><dd>{value}</dd></div>)}</dl><details><summary>Proposal identity</summary><dl className="plans-exact">{Object.entries(proposal.exact).map(([key, value]) => <div key={key}><dt>{key.replaceAll("_", " ")}</dt><dd>{String(value ?? "")}</dd></div>)}</dl></details>{proposal.assumptions.length ? <ul>{proposal.assumptions.map((assumption) => <li key={assumption}>{assumption}</li>)}</ul> : null}{controls ? <div className="button-row"><button className="primary-button" aria-disabled={busy} aria-describedby={busy ? waitingId : undefined} onClick={() => void act(() => controls.confirm(proposal.id))}>Confirm exact proposal</button><button className="secondary-button" aria-disabled={busy} aria-describedby={busy ? waitingId : undefined} onClick={() => void act(() => controls.decline(proposal.id))}>Set proposal aside</button></div> : null}{busy ? <p id={waitingId} role="status">Waiting for the vault…</p> : null}</section>;
}

function CreatePlan({ controls, initialDraft = null }: { controls: PlanControls; initialDraft?: PlanDraftResult | null }) {
  const waitingId = "plans-create-waiting";
  const seeded = initialDraft?.state === "settled" ? initialDraft.draft : null;
  const seededText = (key: string) => typeof seeded?.payload[key] === "string" ? seeded.payload[key] as string : "";
  const seededDay = typeof seeded?.payload.contribution_day === "number" ? seeded.payload.contribution_day : "";
  const [title, setTitle] = useState(seededText("title"));
  const [target, setTarget] = useState(seededText("target_amount"));
  const [currency, setCurrency] = useState(seededText("currency") || "USD");
  const [date, setDate] = useState(seededText("target_date"));
  const [monthly, setMonthly] = useState(seededText("monthly_contribution"));
  const [day, setDay] = useState<number | "">(seededDay);
  const [draft, setDraft] = useState<PlanDraftResult | null>(initialDraft);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const next = initialDraft?.state === "settled" ? initialDraft.draft : null;
    const read = (key: string) => typeof next?.payload[key] === "string" ? next.payload[key] as string : "";
    setTitle(read("title")); setTarget(read("target_amount")); setCurrency(read("currency") || "USD");
    setDate(read("target_date")); setMonthly(read("monthly_contribution"));
    setDay(typeof next?.payload.contribution_day === "number" ? next.payload.contribution_day : "");
    setDraft(initialDraft);
  }, [initialDraft]);
  const payload = (): PlanPayload => ({ verb: "create", title, currency, target_amount: target, ...(date ? { target_date: date } : {}), ...(monthly ? { monthly_contribution: monthly } : {}), ...(day !== "" ? { contribution_day: day } : {}) });
  async function calculate(event: FormEvent) { event.preventDefault(); if (busy) return; setBusy(true); try { setDraft(await controls.draft(payload())); } finally { setBusy(false); } }
  async function keep() { if (busy || draft?.state !== "settled" || draft.kind !== "ready" || !draft.draft) return; setBusy(true); try { const exact = { verb: draft.draft.verb, ...draft.draft.payload }; await controls.propose(exact); setDraft(null); } finally { setBusy(false); } }
  const ready = draft?.state === "settled" && draft.kind === "ready" ? draft.draft : null;
  return <section className="feature-panel plans-create" aria-labelledby="plans-create-title"><div className="section-heading"><div><span className="eyebrow">New save-up plan</span><h2 id="plans-create-title">Calculate a draft</h2></div></div>
    <form className="plans-form" aria-labelledby="plans-create-title" onSubmit={calculate}>
      <label>Plan name<input required value={title} onChange={(e) => setTitle(e.target.value)} /></label>
      <label>Target amount<input required inputMode="decimal" value={target} onChange={(e) => setTarget(e.target.value)} /></label>
      <label>Currency<input required maxLength={3} value={currency} onChange={(e) => setCurrency(e.target.value.toUpperCase())} /></label>
      <label>Target date, optional<input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label>
      <label>Monthly contribution, optional<input inputMode="decimal" value={monthly} onChange={(e) => setMonthly(e.target.value)} /></label>
      <label>Contribution day, 1–28<input type="number" min="1" max="28" value={day} onChange={(e) => setDay(e.target.value === "" ? "" : e.target.valueAsNumber)} /></label>
      <button className="primary-button" type="submit" aria-disabled={busy} aria-describedby={busy ? waitingId : undefined}>{busy ? "Calculating…" : "Calculate draft"}</button>
    </form>
    {draft?.state === "settled" ? <div className={`plans-action-state ${draft.kind}`} role="status"><strong>{draft.message}</strong>{draft.reason ? <span>{draft.reason.replaceAll("_", " ")}</span> : null}</div> : null}
    {ready ? <div className="plans-draft"><h3 id="plans-draft-title" tabIndex={-1}>Draft review</h3><dl><div><dt>Target</dt><dd>{String(ready.payload.target_amount)} {String(ready.payload.currency)}</dd></div><div><dt>Reserved now</dt><dd>{ready.calculated.reserved}</dd></div><div><dt>Remaining</dt><dd>{ready.calculated.remaining}</dd></div><div><dt>Required monthly</dt><dd>{ready.calculated.required_monthly || "Not available"}</dd></div><div><dt>Projected completion</dt><dd>{ready.calculated.projected_completion_date || "Not scheduled"}</dd></div><div><dt>Status</dt><dd>{ready.calculated.status.replaceAll("_", " ")}</dd></div></dl><p>Nothing has been recorded. Keeping this next holds the exact proposal for a separate confirmation.</p><button className="secondary-button" type="button" onClick={() => void keep()} aria-disabled={busy} aria-describedby={busy ? waitingId : undefined}>Hold exact proposal</button></div> : null}
    {busy ? <div id={waitingId} role="status">Waiting for the vault…</div> : null}
  </section>;
}

function GoalActions({ goal, controls }: { goal: GoalPlanView; controls: PlanControls }) {
  const waitingId = `plan-actions-waiting-${goal.id}`;
  const eligible = goal.accounts.filter((row) => row.eligible);
  const accountIds = [...new Set([...eligible.map((row) => row.id), ...goal.history.map((row) => row.accountId)])];
  const [accountId, setAccountId] = useState(accountIds[0] ?? "");
  const [amount, setAmount] = useState("");
  const [busy, setBusy] = useState(false);
  async function propose(payload: PlanPayload) { if (busy) return; setBusy(true); try { await controls.propose(payload); } finally { setBusy(false); } }
  function submitReserve(event: FormEvent, verb: "reserve" | "release") { event.preventDefault(); if (!accountId || !amount) return; void propose({ verb, goal_id: goal.id, account_id: accountId, amount, ...(verb === "release" ? { reason: "used_elsewhere" } : {}) }); }
  return <details className="plans-actions"><summary>Plan actions</summary><div className="plans-action-grid">
    {goal.actions.includes("reserve") ? <form aria-label={`Reserve locally for ${goal.title}`} onSubmit={(e) => submitReserve(e, "reserve")}><strong>Reserve locally</strong><label>Account<select value={accountId} onChange={(e) => setAccountId(e.target.value)}>{eligible.map((row) => <option key={row.id} value={row.id}>{row.name} — {row.availableDisplay} available</option>)}</select></label><label>Amount<input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label><button className="secondary-button" aria-disabled={busy} aria-describedby={busy ? waitingId : undefined}>Review reservation</button></form> : null}
    {goal.actions.includes("release") ? <form aria-label={`Release locally from ${goal.title}`} onSubmit={(e) => submitReserve(e, "release")}><strong>Release locally</strong><label>Account<select value={accountId} onChange={(e) => setAccountId(e.target.value)}>{accountIds.map((id) => <option key={id}>{goal.accounts.find((row) => row.id === id)?.name || id}</option>)}</select></label><label>Amount<input inputMode="decimal" value={amount} onChange={(e) => setAmount(e.target.value)} /></label><button className="secondary-button" aria-disabled={busy} aria-describedby={busy ? waitingId : undefined}>Review release</button></form> : null}
    {goal.actions.includes("change_terms") ? <ChangeTerms goal={goal} controls={controls} /> : null}
    {(["pause", "resume", "set_aside"] as const).filter((verb) => goal.actions.includes(verb)).map((verb) => <button key={verb} className="secondary-button" type="button" aria-disabled={busy} aria-describedby={busy ? waitingId : undefined} onClick={() => void propose({ verb, goal_id: goal.id })}>Review {verb.replace("_", " ")}</button>)}
  </div>{busy ? <div id={waitingId} role="status">Waiting for the vault…</div> : null}</details>;
}

export function Plans({ result, controls, initialDraft = null, receipt = null, onOpenEvidence }: Props) {
  return <PanelStateView result={result} copy={{ partial: "Some plan detail could not be read completely.", needsInput: "A plan needs more input.", unavailable: { title: "Plans are unavailable", detail: "This build did not provide the Plans read." }, failed: { title: "Plans could not be read", detail: "The vault remains unchanged." } }}>{(data) => <div className="plans-surface">
    {receipt ? <div id="plan-action-outcome" className="plans-action-state" role="status" tabIndex={-1}>{outcomeMessage(receipt)}</div> : null}
    {controls ? <CreatePlan controls={controls} initialDraft={initialDraft} /> : null}
    {!data.goals.length && !data.proposals.length ? <section className="feature-panel empty-state"><strong>{data.invitation.title}</strong><span>{data.invitation.body}</span></section> : null}
    {data.proposals.map((proposal) => <ProposalCard key={proposal.id} proposal={proposal} controls={controls} />)}
    {data.goals.map((goal) => <article className="feature-panel goal-card" key={goal.id}><header><div><span className="eyebrow">{goal.statusLabel}</span><h2>{goal.title}</h2></div><strong>{goal.targetDisplay}</strong></header><p>{goal.headline}</p><p>{goal.explanation}</p><dl className="goal-metrics"><div><dt>Reserved</dt><dd>{goal.reservedDisplay}</dd></div><div><dt>Remaining</dt><dd>{goal.remainingDisplay}</dd></div><div><dt>Target date</dt><dd>{goal.targetDate || "No target date"}</dd></div><div><dt>Recorded monthly</dt><dd>{goal.monthlyDisplay || "Not scheduled"}</dd></div><div><dt>Required monthly</dt><dd>{goal.requiredMonthlyDisplay || "Not available"}</dd></div><div><dt>Projected completion</dt><dd>{goal.projectedCompletionDate || "Not scheduled"}</dd></div><div><dt>Deviation</dt><dd>{goal.deviationDisplay || "Not available"}</dd></div><div><dt>Next</dt><dd>{goal.nextContributionDate || "No planned date"}</dd></div></dl><p className="quiet-note">{goal.noMoneyMoved}</p>{goal.assumptions.length ? <div><strong>Assumptions</strong><ul>{goal.assumptions.map((row) => <li key={row}>{row}</li>)}</ul></div> : null}{goal.caveats.length ? <div><strong>Caveats</strong><ul>{goal.caveats.map((row) => <li key={row}>{row}</li>)}</ul></div> : null}<details><summary>Availability and evidence</summary>{goal.accounts.map((account) => <div className="goal-account" key={account.id}><strong>{account.name}</strong><span>{account.sentence}</span>{account.dated ? <span>Evidence date: {account.dated}</span> : null}{account.balanceExplanation ? <span>{account.balanceExplanation}</span> : null}{account.gradeDescription ? <span>{account.gradeDescription}</span> : null}{account.caveats.map((row) => <span key={row}>{row}</span>)}{account.evidenceLinks.map((link) => <button className="text-button" key={`${link.targetDocumentId}-${link.page}`} onClick={() => onOpenEvidence(link)}>Open {link.label || "source document"}</button>)}</div>)}</details><details><summary>Reservation history</summary>{goal.history.some((row) => row.valid) ? goal.history.filter((row) => row.valid).map((row, index) => <p key={`${row.occurredAt}-${index}`}>{row.sentence}</p>) : goal.history.length ? <p>{goal.historyNote}</p> : <p>No reservation activity is recorded.</p>}</details>{controls && goal.actions.length ? <GoalActions goal={goal} controls={controls} /> : null}</article>)}
  </div>}</PanelStateView>;
}
