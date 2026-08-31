# Jobs and the Progress Channel

**State:** built
**Rules:** none

## Rules

This document still owns no independent rule ids. It records the constraints of
the job registry, sidecar channel, host subscriber and desktop session; their
executable contracts and tests live with those modules. A future rule block
belongs here only if jobs acquire a new standing product rule rather than
another producer using the existing mechanism.

## Why

### The channel and its producers

The desktop window does not hold a person's financial data. A bundled
background process — the sidecar — holds the vault, and the window asks it
questions over a pipe. Most of those questions are quick: ask, wait, get an
answer. Some work is not like that. Reading a folder of documents produces many
units of work from one gesture, takes long enough that a person will wonder
whether anything is happening, and can finish some parts while others are still
running. Work of that kind is a **job**, and a job needs a way to say what it is
doing while it is doing it. That way is the progress channel.

Document work and paid maintenance now produce jobs. The sidecar mints an
identity, the registry records named steps, and progress frames travel through
the host's event subscriber into the desktop session. Terminal progress causes
the session to reread the financial surfaces and the job registry rather than
patching either from an event. Bounded receipts are also available through the
reviewed jobs read.

### A job's identity is minted by the sidecar, and the caller's request id travels beside it

The registry mints a monotonically numbered identity scoped to the operation.
The caller never asserts it; action payloads contain the work's inputs, and the
result or progress frame carries the resulting job id.

Correlation then needs two fields rather than one, and they answer different
questions. The **request id** answers *which of my calls is this about*, and the
caller mints it, as it already does. The **job id** answers *which unit of work
is this about*, and the sidecar mints it. Every event carries both. They are not
interchangeable: the transport request belongs to a vault session, while a job
can continue after the action reply and is read later from the registry.

The caller-asserted field was removed when this meaning changed, and the wire
advanced to protocol `2.0`. That major step is already taken; a future producer
reuses the sidecar-minted identity rather than advancing the protocol again.

### An event goes to a subscriber, never through a filter inside a blocking read

The host now owns one sidecar-output reader. It routes an answer to the request
waiting for it and publishes a progress frame to the window event subscriber,
so a blocked request does not consume another request's event.

The shape that works is one reader owned by the host, which sorts frames as they
arrive: an answer goes to the request that is waiting for it, and an event goes
to whoever subscribed to events. The lock then guards only the writing side, and
requests stop queueing behind each other by accident.

This is a structural point rather than a preference: **a filter inside a caller
can only ever be correct when there is exactly one caller.** New producers reuse
the host subscriber rather than adding another pipe reader.

### A state joins the closed vocabulary in the module that owns it, and only when something can produce it

The words a job may use about itself are a closed set living in one module, and
they stay that way — never a free-text field, never a string a caller may invent.
A vocabulary that anything can add to is not a vocabulary; it is a place where
two spellings of the same idea end up meaning different things in two branches of
the same window.

The set grows only when something can produce the new word, and it grows in the
module that owns it rather than in a caller that wants to render it. Job records
use `queued`, `running`, `completed`, `failed` and `cancelled`. Progress frames
use `started`, `progress`, `completed`, `failed` and `cancelled`; adapters reject
anything outside those closed sets.

### A fraction ships only from a producer that knows its denominator

Progress that reads "forty-two of two hundred" is worth a great deal, and
progress that reads "none of one" and then "one of one" is worth less than
nothing, because it looks like measurement. The invariant this project already
holds — **uncertainty is visible, never decorative** — is written about money,
and it transfers exactly: a total of `1` asserted by code that counted nothing is
a number with nothing behind it.

So a fraction ships only from a producer that genuinely knows its denominator,
and a producer that does not know it **says so by omitting it, never by inventing
one**. A bare count moving upward with no total is honest; a bar that runs from
empty to full in one tick is decoration.

Two guards follow, because both will otherwise be reinvented.

A progress count is not a financial figure and must never become one. This
project sorts a number by asking *what would a wrong number here move?* — the
person's money makes it financial, the agent's account of its own records makes
it activity. "Forty-two of two hundred documents read" is the agent's account of
its own work. It carries no confidence grade, and it must not acquire one by
being displayed next to money.

And a duration is not automatically a progress opportunity. Opening a vault is
two costs in sequence, and only one of them can speak. First the passphrase is
turned into an encryption key by a computation that is slow and memory-hungry on
purpose, so that guessing passphrases is expensive; that cost is the same whether
the vault is empty or full. Then the encrypted log is decrypted and replayed to
rebuild the current picture, and that cost grows with the size of the log.

The second has a countable unit. **The first has no intermediate state at all, by
construction** — a memory-hard key derivation is a single computation with
nothing meaningful to report from inside it. That is a fact about how the
function is built and not a measurement, so it does not change when the vault
grows, when the machine gets faster, or when a different vault is opened. A
counter over the replay therefore describes one of the two costs and leaves a
person watching an unstarted bar through the other, and how long that stretch is
relative to the whole depends on which vault is being opened.

The rule that follows is about where a channel is pointed. Before instrumenting
something slow, the question is not *how long does this take*, which is a fact
about one vault on one machine on one day. It is **which phase is the time in,
and can that phase say anything true about itself** — and where a phase cannot,
no proportion makes a bar over the other phase honest.

### Nothing on this channel is ever appended to the financial event log

The event log is the spine of this product: every state change is a record in an
append-only chain, each record embedding the previous record's hash, and current
state is a projection of that log rather than an independent authority. Its whole
value is that everything in it is a claim about the past that was checked.

Job progress is not a state change in the vault. It is transport ephemera about
work in flight — true for a second, uninteresting afterwards, and interesting
again only in aggregate, which is a different question with a different answer.
Writing it into the log would put unchecked chatter into the one structure whose
worth is that it contains nothing unchecked, and it would grow without bound in
the file a person most needs to stay small and verifiable.

Nothing on this channel is appended to the financial log. What a completed job
*did* — a document captured, a movement posted — is an event, written by the
code that did the thing, in the ordinary way. The bridge may persist a bounded
`.jobs.json` receipt beside the vault containing operation, state, step, counts
and message. It contains no financial or document values and is not an authority
for projection state.

## Open

- **Interrupted work is not resumed.** A nonterminal durable receipt is restored
  as failed with an instruction to start the operation again. Resumable step
  checkpoints and idempotent continuation remain unbuilt.
- **Cancellation is cooperative between named steps.** It cannot interrupt the
  inside of a blocking reader or model call; the next checkpoint observes it.
- **The jobs read remains operational rather than a registry destination.** It
  is shipped and reviewed, but no navigation capability claims it as a separate
  destination.
- **How long an open takes has been measured on two vaults and on one machine,
  and on nothing else.** Across the author's own baseline vault and the largest
  vault he holds, an open took roughly four tenths of a second to eight tenths
  end to end. Those two numbers describe those two vaults; the split between the
  fixed key-derivation cost and the size-dependent replay differs between them,
  and the balance moves further as a log grows. No proportion is carried forward
  from them, and any future argument that leans on one states the vault it was
  measured on and the spread across vaults.
- **Nothing has been measured near the size at which an open would become slow
  enough to be worth reporting at all.** Extrapolating the point from two vaults
  would be a projection dressed as a finding; the honest position is that the
  question is re-asked against real vaults when one is much larger, not
  inherited.
