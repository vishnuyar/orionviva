# Shipped merchant knowledge

Committed, distributed with the package, and **read-only in practice**. This is
the seed every installation starts with, so a new person's first month costs
nothing for knowledge somebody has already paid a model to learn.

- `profiles/` — induced bank grammars: slots and literals, no values. A grammar
  is verifiable by anyone against their own statement (`induce_profile --verify`),
  which is the check a merchant catalog cannot offer.
- `catalog.json` — merchant records: a brand, a category, impersonal attributes.

**Nothing lands here automatically.** What an installation learns is written
*outside the working tree* (`~/.merchantcore/`, or `MERCHANTCORE_HOME`), and
promotion into this directory is a deliberate act by a person.

That is not bureaucracy. A grammar's literal text comes from a model, and the
one check that catches a person's name baked into it is a human reading the
templates — every automated gate measures whether a template *matched*, never
whether it *slotted correctly*. A grammar published here is published to
everybody, so it is the one place where reading is not optional.

Empty is the correct state until the first grammar is ratified.
