# Shipped merchant knowledge

Committed, distributed with the package, and **read-only in practice**. This is
the seed every installation starts with, so a new person's first month costs
nothing for knowledge somebody has already paid a model to learn.

- `profiles/` — induced bank grammars: slots and literals, no values. A grammar
  is verifiable by anyone against their own statement (`induce_profile --verify`),
  which is the check a merchant catalog cannot offer.
- `catalog.json` — a `merchant-catalog-v2` pack of privacy-linted business
  records. Each permanent merchant id carries reviewed, normalized exact aliases,
  a category and impersonal attributes. Peer and financial-instrument records do
  not ship; occurrence cities, store numbers, amounts and account data never
  become aliases.

An alias is identity authority, so adding one is a review decision. Models and
equal display names cannot create a fold. The first pack intentionally folds only
`costco whse` into id `costco` (`costco`, `costco at`, `costco whse`); Costco Gas
and the existing web-shaped records remain distinct.

Legacy records whose self-key retained an occurrence location, branch wording or
store marker are withheld from this first pack unless that wording is part of the
reviewed merchant identity. Being a typed business is necessary for publication,
but it is not enough to turn occurrence context into a reusable alias.

**Nothing lands here automatically.** What an installation learns is written
*outside the working tree* (`~/.merchantcore/`, or `MERCHANTCORE_HOME`), and
promotion into this directory is a deliberate act by a person.

That is not bureaucracy. A grammar's literal text comes from a model, and the
one check that catches a person's name baked into it is a human reading the
templates — every automated gate measures whether a template *matched*, never
whether it *slotted correctly*. A grammar published here is published to
everybody, so it is the one place where reading is not optional.

The catalog now carries the first ratified business seed. The profiles directory
remains empty until the first statement grammar is independently verified and
ratified.
