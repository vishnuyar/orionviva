# Contributing to OrionViva

Thank you for considering it. This project is early and moving fast — open an
issue to discuss before large changes, so neither of us spends a weekend on
something the other was already rewriting.

Given the subject matter, security- and privacy-minded review is the most
valuable thing you can send. Finding a hole in the encryption, the key custody,
or the verification layer is worth more here than a feature.

## Sign your commits (DCO)

Contributions are accepted under the [Developer Certificate of Origin][dco] —
a one-line statement that you wrote the patch, or otherwise have the right to
submit it under this project's MIT license. There is no CLA to sign, and you
keep the copyright in what you write.

Add the sign-off by committing with `-s`:

```
git commit -s -m "Your commit message"
```

which appends:

```
Signed-off-by: Your Name <your.email@example.com>
```

The name and email must be real and match your commit author. Every commit in
a pull request needs one; a CI check enforces it. Forgot on the last commit?
`git commit --amend -s`. On several? `git rebase --signoff main`.

Why DCO and not a CLA: a CLA would ask you to grant rights broad enough to
relicense your work later, which is a strange thing to ask from contributors to
a project whose entire pitch is that you never have to take a promise on faith.
The reasoning is written up in [ADR-009](docs/decisions/ADR-009-dco-contributions.md).

## Trust-critical changes get adversarial review

Some code in this project is load-bearing for the one promise that matters:
that an answer about your money can be believed without re-checking it. Changes
touching these areas are reviewed adversarially — the reviewer's job is to try
to break the guarantee, not to approve the diff:

- **The verification layer** — anything affecting how a figure earns its
  confidence grade, or how arithmetic is checked.
- **Cryptography and key custody** — encryption at rest, the crypto envelope,
  anything that touches a key.
- **The event log** — append-only semantics, the hash chain, anchoring.
- **Anything that sends bytes off the machine.** The outbound surface is
  deliberately tiny (see [ADR-006](docs/decisions/ADR-006-zero-exfiltration.md));
  adding to it is a decision, not an implementation detail.

Expect these reviews to be slow and to ask uncomfortable questions. That is the
review working, not the reviewer being difficult. A change here that is merely
*probably* correct is a change that isn't ready.

If you think a change touches one of these areas, say so in the pull request —
it speeds things up rather than slowing them down.

## Ground rules that apply to every change

These come from the project's decision records and aren't up for negotiation in
a pull request (they're up for negotiation in an *issue*, which is the right
place to argue with an ADR):

- **No number without a source and a confidence signal.**
- **Arithmetic is deterministic** — never performed inside a model.
- **No plaintext persistence of personal financial data**, including in tests,
  fixtures, and debug output.
- **No telemetry, analytics, or crash reporting** that phones home.
- **Never commit real financial data.** Not yours, not anyone's, not
  "anonymized." Test fixtures are synthetic.

## Reporting a security issue

Please don't open a public issue for a vulnerability. Email the maintainer
directly and give a reasonable window to fix it before disclosure. Security
reports are welcome and will be credited unless you'd rather they weren't.

## Where to read first

`docs/` holds the project's thinking — start with
[docs/reading-guide.md](docs/reading-guide.md). The decisions and their
reasoning live in [docs/decisions/](docs/decisions/README.md); if you disagree
with one, the ADR names what would reverse it, which is the most useful place
to aim an argument.

[dco]: https://developercertificate.org/
