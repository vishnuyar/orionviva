# WORKFLOW — how this project is built

**Status:** Living · **Last updated:** 2026-07-30

OrionViva is built by a product owner who directs, and an AI that engineers.
This file is the contract between them: the roles, the loop, and the gates.
Any session working in this repo — Cowork or Claude Code — follows it. The
roles live as files in `.claude/agents/`; each file is the full instruction
set for that role, and this document says when each role runs.

## The crew

**Design Partner** — turns an idea or a diagnosed bug into a design brief:
options with detailed viewpoints in prose, invariants touched, doors named,
one recommendation, a scope fence, and the questions only the product owner
can answer. Produces briefs, never code.

**Builder** — implements an approved brief, nothing more. Follows the standing
practices (prompts as files, no word lists, comments describe behavior, read
side early). Ends every session with a plain-language walkthrough: what
changed, why, what is now observable, how to see it, what was left undone.
Never commits.

**Verifier** — a fresh context that did not build the code. Runs the full
suite, runs the change against real documents where it can, and checks the
diff did *only* what the brief said. Reports findings; fixes nothing. The
builder never grades its own work — that separation is the point.

**Steward** — the ship-time rituals once verified work is accepted: comment
style pass, reading-guide and docs impact pass, TODO update, the paranoia
grep, and a drafted commit message with no tool footers. Then it stops.

**Tutor** — explains any part of the system at any depth, changing nothing.
The role to reach for whenever the code has outrun understanding — which is a
normal state here, not a failure.

**Reporter** — turns an observed problem into a GitHub issue: a short
intake, read-only diagnosis of the likely area, a severity in this project's
terms, a duplicate check, and a draft scrubbed of every real value and name
before it exists. The issue is filed only on the product owner's explicit
word — public speech gets the commit gate's treatment — and the fix begins
later as its own full-lane cycle ("design phase: issue #N").

## The loop (full lane)

1. **Idea or bug** → Design Partner produces a brief.
2. **Checkpoint 1 — approve the brief.** The product owner reads the options,
   decides, amends. Nothing is built from an unapproved brief.
3. Builder implements → delivers the walkthrough.
4. Verifier (fresh context) runs → delivers the report.
5. **Checkpoint 2 — accept the work.** Walkthrough plus verification report,
   read together. Findings loop back to the Builder; scope-fence flags loop
   back to the brief.
6. Steward runs the rituals → presents the commit message and stops.
7. **Checkpoint 3 — the commit gate.** Only the product owner says commit.
   No commit happens without those words, ever.

Every bug found in use goes through this full lane. Its intake is the
Reporter: the bug becomes a scrubbed public issue first, so known problems
are record rather than memory, and the Design Partner step then starts from
the issue — a bug whose cause is understood is a design decision about what
should be true, and gets the same treatment. Verifier findings accepted but
not fixed immediately are offered to the Reporter too.

## The fast lane

For small changes with **no behavior change**: typos, comment or doc wording,
formatting, a rename with no semantic edit. The brief is skipped; the Builder
states in one paragraph what it is about to do and why it is fast-lane, then:
Builder → Verifier → commit gate. The Verifier's scope check applies with full
force — the moment a "small fix" turns out to touch behavior, an event, a
schema, a prompt, or an invariant, it bounces up to the full lane. When in
doubt, full lane.

## The hard gates (scripts, not promises)

Roles are prompts; anything that must never happen is enforced by code:

- `.githooks/pre-commit` — blocks a commit whose staged changes contain a
  `.denylist` entry or an account-number-like digit run. Enable once per
  clone: `git config core.hooksPath .githooks`. Bypassing with `--no-verify`
  is a deliberate act, done only after the Steward's grep judged a hit
  synthetic.
- The test suites, including the guards that fail the build on prompt
  literals. The suite is green at every checkpoint 2.

## Working practice

- **One cycle per session.** A session carries one brief from idea to commit
  gate (or one lane of it, for large cycles: design in one session, build in
  the next). Long mixed sessions are where scope creep and diluted rules live.
- **The Verifier always gets a fresh context** — a separate subagent, never
  the conversation that built the code.
- **End of session, capture state:** TODO.md current, brief saved if the
  cycle continues, so the next session starts with bearings instead of
  archaeology.
- **In Claude Code**, the roles are native subagents (`/agents` lists them).
  **In Cowork**, say which phase you want — "design phase:", "build from the
  approved brief", "verify the diff", "ship it", "tutor: explain…" — and the
  session reads the matching role file and runs it as that role, spawning a
  fresh subagent for verification.
- The product owner's standing rights: reject any work that arrives without a
  walkthrough, reject any diff that exceeded its brief, and stop any phase to
  ask the Tutor to explain before deciding. Using these rights is the process
  working, not friction.
