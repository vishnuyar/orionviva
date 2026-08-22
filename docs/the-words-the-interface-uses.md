# The Words the Interface Uses

**State:** partial
**Rules:** VOICE-133, VOICE-134, VOICE-135

There is an architecture authority for the desktop application and there has
been no *language* authority for it. This is that: which word names which layer,
and which vocabulary a person is spoken to in. It settles naming only. What the
layers may import, and what a figure must carry to cross between them, stay in
[user-interface-architecture-and-delivery.md](user-interface-architecture-and-delivery.md).

## Rules

### VOICE-133 — five words, five layers, and none of them is a synonym
**State:** untestable
**Code:** none found — the subject is the words prose and component names use, and no source in this repository declares them in one place a check could read
**Test:** none — a naming convention over English has no local source to compare against

1. **The desktop application** is the whole installed thing a person runs: the window, the interface inside it, and the bundled process that holds the vault. It is the product.
2. **The shell** is the native host — the window, the menus, the folder picker, and starting and stopping the sidecar. It holds no financial meaning.
3. **The interface** is the layer a person looks at and touches: screens, panels, focus, copy. This is what *frontend* means, and *interface* is the word to write.
4. **The surface** is `viva.surface`, the contract between the product and the interface — read models, closed vocabularies, the capability registry. It is never a word for something a person can see.
5. **The bridge** is transport: it carries frames and understands none of them.

### VOICE-134 — the interface says receipt; the contract keeps citation
**State:** unmet
**Code:** none found — `Citation`, `provenance` and the `attests`/`corroborates` relation are the contract's and are already correct; the interface half is unbuilt
**Test:** none

1. What a person is shown is called a **receipt**, because that is the demand a person already makes of a claim about money and it needs no teaching.
2. `Citation`, `provenance` and the `attests`/`corroborates` relation do not move. The rename is interface copy and interface component names only, and it does not cross the boundary.
3. A panel that opens onto a figure's sources is named for what it shows rather than for the contract behind it.

### VOICE-135 — `disabled` is reserved for nothing; `aria-disabled` says a control is busy
**State:** contradicted
**Code:** The attribute appears in no JSX under `desktop/src`, and `desktop/scripts/check-ui-boundaries.mjs` holds it out of the whole tree with a self-check that puts one back and asserts the checker goes red. The busy controls carry `aria-disabled` instead and stay focusable — the set-aside controls in `desktop/src/features/review/Review.tsx` and the vault picker and vault-open submit in `desktop/src/app/App.tsx` — each refusing a second press in its own handler and each describing itself, while busy, with a sentence saying that pressing again does nothing until the vault has answered.
**Test:** none — what holds this is a Node gate and tests written in TypeScript, and the rule index collects test names by parsing Python.

**Why the state has not moved.** Nothing in the code contradicts the rule any longer. What the state still records is that no test this repository's rule index can read holds any of it, so `by-review` is the ceiling this rule can reach — and moving the word, even that far, is a judgement about how a rule is known rather than a change to the code, which is the product owner's to make and not a build cycle's.

1. `disabled` is reserved for nothing. A control this screen cannot perform at all does not render, which is VOICE-136's business; a control that renders is one a person can reach.
2. A control this screen can perform, and that is unavailable only while the vault answers the last request, carries `aria-disabled` and stays focusable. A focused element that becomes `disabled` is blurred to the document body, which empties a person's hands at the moment a refusal needs them full.
3. A control carrying `aria-disabled` refuses the second press in its own handler and says in words that it did.

## Why

### Two of the words already meant something, so the interchange was not harmless

*Frontend* and *desktop* were being used for the same thing, and *surface* was
being used for both a contract and a screen. One of those three is a Python
package. "The surface shows five accounts" is a sentence that has been written
meaning two different things, and neither reading is wrong on its face — which
is exactly the property that makes a word unusable in a specification.

Naming the layers separately costs nothing and buys the ability to say where a
problem lives. A window that will not close is the shell's. A panel that reads
as blame is the interface's. A read model missing a field is the surface's. A
frame that never arrived is the bridge's. Before this, all four were "the
frontend".

### The vocabulary that already has states

Two of these words are not opinions; they are declared in code and gated.

- A **destination** is a place in the interface a capability lands: overview,
  accounts, activity, documents, review, viva, trust, settings. The registry
  declares them and a gate compares the declaration against what ships.
- A **capability** is a thing the product can do, carrying a disposition —
  *surfaced*, *developer-only*, *internal* or *deferred* — and, when surfaced, a
  destination and a named contract.

Nothing here renames either. They are recorded because a vocabulary document
that omits the two words that already have machine-readable states would be
teaching a reader half a language.

### Receipt, not evidence

The public site promises *every number has a receipt*, repeatedly and as a
headline. The interface says **evidence** — the badge, the drawer, the target
resolver, the link that opens one.

*Receipt* wins. *Evidence* is courtroom register: it presumes a dispute, and it
sounds like the machine defending itself. For a product whose central problem is
that a person has no reason to believe a number a model was near, the word has
to be the plainest one available, and the plainest one is the one the person
would have used first.

The split is deliberate rather than a compromise. The interface speaks the
site's language because a person reads it; the contract keeps its precise
vocabulary because a program reads it, and `attests` and `corroborates` are
distinctions no everyday word carries. A rename that crossed that line would
trade a precise relation for a friendly one, which is the wrong direction on a
trust boundary.

That is why VOICE-134 is `unmet` rather than `enforced`: the ruling is settled
and the interface has not been changed yet. It is a copy and component pass on
one side of a boundary, and it travels on its own rather than beside a change to
behaviour.

### A control that cannot act is not a disabled control; it is not a control

This rule used to say that a control the screen cannot perform at all carries
`disabled` and leaves the tab order, and that the attribute was how a person
was told the difference between a boundary and a wait. That half is retired.
Removing a dead control from the keyboard's reach does not remove it from the
eye's. It still occupies space, still names an action, and still teaches a
person that the product has a feature — one they will keep pressing, since
nothing on the screen says whether it is unbuilt, unavailable for this account,
or waiting on something they could go and do. A dead control is a promise the
product has no intention of keeping, greyed out and left where the promise can
be read.

The replacement is not a better attribute. It is that the control is not there:
a screen renders what is served and nothing else, which is VOICE-136's
business, and where the absence changes what the person should do next, one
sentence says so, which is VOICE-137's. What that buys is a product that is
small and entirely alive rather than large and mostly inert — and an empty
vault stops looking like a broken application.

The wait is the case that survives, and it is where the attribute distinction
still earns its keep. A control that is busy will work, is working, and the
person may well need that exact control again the instant the wait ends — which
is what a refusal is. It stays under their hands, keeps its focus, and answers
the second press in words rather than by going silent. That is why the
distinction is written down rather than decided per panel: it is not a styling
choice, it decides whether a keyboard reaches the control at all.

Reversing this costs an audit of every control the product will ever ship,
which makes it sticky rather than one-way. Its price has been paid rather than
argued with. The page-review control with nothing behind it was deleted instead
of re-attributed; the capture control renders because an operation now stands
behind it; and the two vault-opening controls that went `disabled` while the
vault answered carry `aria-disabled`, keep their focus and refuse the second
press in words. The **Code** field above says where the rule stands.

### Where the guidelines are thin, and it will show

The naming half is cheap. The craft half is where drift comes from, and this
document does not close it. `desktop/src/styles/tokens.css` now holds a type
scale, a spacing scale, radii, motion durations and easings, icon sizes and a
dark palette nothing turns on — but the screen-specific stylesheets beside it
are still an order of magnitude longer than the tokens they draw on, and still
carry the raw values they were written with. Accessibility is genuinely
practiced: aria attributes across the features and shared components,
focus-management tests, role queries in most suites. What fails a build is
narrower than that: a stylesheet declared to be written against the token set
may hold no raw value, the two older stylesheets may not gain any, and the
sentences the capture screen and the overview's picture ship are measured
against the contrast floor, along with every paint a person has to see in
order to follow the picture.
Keyboard reach is still held by habit.

The interface has an architecture gate and half a craft gate. Naming a gap here
is not the same as closing it, and no rule in this document pretends otherwise.

That territory carries a rule, VOICE-140 in
[surface-charter.md](surface-charter.md), which asks for a type scale, a
spacing scale, motion rules, dark mode, iconography and keyboard reach as
conditions a new surface ships against. The token half is built and runs in the
desktop job; the keyboard check is not, and the rule stays unmet on its second
clause while the older stylesheets hold values no token names. What the gate
reports is how many, so the shortfall is a number rather than a confession.
