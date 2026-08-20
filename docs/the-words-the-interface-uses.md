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

### VOICE-135 — `disabled` says a control is not here; `aria-disabled` says it is busy
**State:** contradicted
**Code:** `desktop/src/features/documents/Documents.tsx:13` marks a capture control `disabled`, because nothing behind that screen captures anything. `desktop/src/features/review/Review.tsx:66` marks the set-aside controls `aria-disabled` while the vault answers the last request. `desktop/src/app/App.tsx:243` sets `disabled` on the two vault-opening controls while a vault is opening, which is the busy case wearing the other attribute.
**Test:** none

1. A control this screen cannot perform at all carries `disabled`. There is nothing behind it to reach, so it leaves the tab order.
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

### Two ways for a control to be unavailable, and only one of them is permanent

A screen that cannot do a thing and a screen that is in the middle of doing it
look the same to a person for a moment, and they are not the same. The first is
a boundary: pressing it would never have worked, and the control is dead weight
in the tab order. The second is a wait: it will work, it is working, and the
person may well need that exact control again the instant the wait ends —
which is what a refusal is. Taking focus away at that moment is the interface
answering for them.

That is why the distinction is written down rather than decided per panel. The
attribute is not a styling choice; it decides whether a keyboard reaches the
control at all.

### Where the guidelines are thin, and it will show

The naming half is cheap. The craft half is where drift comes from, and this
document does not close it. `desktop/src/styles/tokens.css` defines colour
tokens and nothing else — no type scale, no spacing scale, no motion rule, no
dark mode — and the screen-specific stylesheet beside it is an order of
magnitude longer than the tokens it draws on. Accessibility is genuinely
practiced: aria attributes across the features and shared components,
focus-management tests, role queries in most suites. But it is practiced by
habit, and nothing fails a build when the next panel forgets.

The interface has an architecture gate and no craft gate. Naming it here is not
the same as closing it, and no rule in this document pretends otherwise.
