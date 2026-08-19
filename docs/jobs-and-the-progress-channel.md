# Jobs and the Progress Channel

**State:** design-only
**Rules:** none

## Rules

This document defines no rules and states no behaviour the code can be held to,
because the thing it describes has no producer yet. It fixes the shape of a
channel before the first piece of work that could feed one exists, so that the
shape is decided calmly rather than in the middle of building something else.

Rule blocks arrive with the machinery, in the document that specifies whatever
first produces job progress. That is deliberate and not an omission: a rule
block in this folder carries a state, the code that implements it and the test
that pins it, and a rule whose state would have to read "nothing implements
this" is a promise wearing the clothes of a fact.

## Why

### The channel, and why it is empty

The desktop window does not hold a person's financial data. A bundled
background process — the sidecar — holds the vault, and the window asks it
questions over a pipe. Most of those questions are quick: ask, wait, get an
answer. Some work is not like that. Reading a folder of documents produces many
units of work from one gesture, takes long enough that a person will wonder
whether anything is happening, and can finish some parts while others are still
running. Work of that kind is a **job**, and a job needs a way to say what it is
doing while it is doing it. That way is the progress channel.

Today the channel is built along most of its length and connected at neither end
that matters: the sidecar writes progress frames, the native host reads them and
throws them away, and nothing in the window has ever received one. The only work
that emits anything is a surface read that reports "none of one" and then "one
of one" — a job with no reportable state, which can only be rendered as a
spinner or as a lie.

The channel is therefore not finished as it stands. It is designed with its
first real producer, document ingest, and the five constraints below bind
whoever does that. They are stated as constraints rather than as a design,
because the design belongs with the producer and these are the parts that should
not be re-argued when it arrives.

### A job's identity is minted by the sidecar, and the caller's request id travels beside it

The window currently invents a name for the job and the sidecar echoes it back.
That is the shell telling the backend what a backend thing is called, and it
fails in two ordinary ways: two callers that both leave the name out get the same
name, and a caller cannot know whether the request it just made started one unit
of work or five. Ingest is exactly the case where one call starts several.

So identity is minted by the party that knows what a unit of work is, which is
the sidecar. The caller never asserts it, and the request stops accepting one.

Correlation then needs two fields rather than one, and they answer different
questions. The **request id** answers *which of my calls is this about*, and the
caller mints it, as it already does. The **job id** answers *which unit of work
is this about*, and the sidecar mints it. Every event carries both. They coincide
today only because one call means one job; they come apart the first time one
call starts several jobs, or a job outlives the call that started it, which is
the whole shape of ingest.

Changing that field from caller-asserted to sidecar-minted changes what the field
means, and the protocol rule this project already holds says that *"additive
optional fields advance the minor version; removing a field or changing its
meaning advances the major."* So it is a major version step. It is taken once, at
the moment the field actually changes, and not twice if another contract change
lands in the same cycle.

### An event goes to a subscriber, never through a filter inside a blocking read

The current arrangement hands every frame to whichever request happens to be
blocked reading the pipe, and that request discards anything that is not the
answer it is waiting for. With one request in flight this is merely wasteful.
With two it is a correctness bug that cannot be fixed where it lives: the second
request's loop consumes and discards the first request's events, and the first
never sees them, because only one loop is reading.

The shape that works is one reader owned by the host, which sorts frames as they
arrive: an answer goes to the request that is waiting for it, and an event goes
to whoever subscribed to events. The lock then guards only the writing side, and
requests stop queueing behind each other by accident.

This is a structural point rather than a preference: **a filter inside a caller
can only ever be correct when there is exactly one caller.** Whatever produces
the first real progress, this is the change it needs.

### A state joins the closed vocabulary in the module that owns it, and only when something can produce it

The words a job may use about itself are a closed set living in one module, and
they stay that way — never a free-text field, never a string a caller may invent.
A vocabulary that anything can add to is not a vocabulary; it is a place where
two spellings of the same idea end up meaning different things in two branches of
the same window.

The set grows only when something can produce the new word, and it grows in the
module that owns it rather than in a caller that wants to render it. The
temptation is always to add words in advance so the vocabulary looks ready — a
word for work a person stopped, a word for work the machine will attempt again.
Neither is here, and neither is named as a candidate, because **a state nothing
can produce is the same defect as a channel nothing consumes**: a word that looks
like a capability. Each arrives with the machinery that can emit it, in the brief
that builds it.

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

### Nothing on this channel is ever appended to the event log

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

Nothing on this channel is ever appended. What a completed job *did* — a document
captured, a movement posted — is an event, written by the code that did the
thing, in the ordinary way. That the job reached its end is not.

## Open

- **The channel has no producer.** The first is document ingest, and it is
  designed there. Until then the wire remains as it is: the sidecar writes
  frames, the native host reads and discards them, and nothing in the window
  subscribes. None of the constraints above is implemented anywhere.
- **Whether a job that outlives the call that started it needs a registry** —
  somewhere to look up a job by its id after the request has returned — is
  undecided. It is the obvious next question once identity is minted by the
  sidecar, and it is not answered here because nothing yet produces a job that
  outlives its call.
- **How the window renders a job it did not start** is undecided for the same
  reason. Nothing here says what a panel does when an event arrives for work the
  person did not initiate from that panel.
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
- **This document has no slot in the reading guide.** It needs one, and the
  Steward places it. Nothing checks that a new document is slotted anywhere, so
  an unreferenced document is a real outcome rather than a hypothetical one.
