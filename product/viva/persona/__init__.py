"""Viva's voice lives here, as data — the persona pack.

Everything Viva says is an entry in a versioned pack directory, never a Python
literal. The discipline is prompts-as-files applied to the persona: her whole
vocabulary is reviewable in one sitting, a wording change is a pack change (a
NEW version once a pack is released — a recorded ``pack_version`` must keep
resolving, exactly as a recorded ``prompt_version`` must), and a test keeps
question text out of code the same way ``test_no_prompt_text_lives_in_code``
keeps prompts out.

Three hard rules, enforced mechanically (test_persona_pack.py):

1. **A phrasing may not introduce a fact.** Every ``{slot}`` in a template must
   name a field the deterministic question intent supplies — ``INTENT_FIELDS``
   below is that contract. The queue decides WHAT is said (figures, evidence,
   options); the pack only decides HOW it sounds. A phrasing's failure mode is
   *stiff*, never *false*.
2. **A slot says what it holds.** The contract is typed, so a hole in a sentence
   names a kind of thing in the world rather than only a word. An amount is a
   value and a currency written under one locale's conventions, and a slot
   asking for one cannot be handed a bare number — the type is checked where the
   sentence is made, not hoped for at review.
3. **Rendering is strict.** A template referencing a slot the caller didn't
   supply raises immediately rather than rendering a hole — a question with a
   blank where a figure should be is a bluff by omission.

The pack is impersonal by construction: it contains no user data, so it is
shareable, reviewable in a PR, and swappable — a terser Viva, or another
language, is a pack, not a code change.
"""

from __future__ import annotations

import json
import pathlib
import string
from functools import lru_cache

from vivacore import versions

from ..render import (ACCOUNT, CATEGORY, COUNT, DATE, DOCUMENT, MERCHANT,
                      MONEY, PROSE, RENDERED)

_DIR = pathlib.Path(__file__).resolve().parent

# The voice currently speaking, as `viva/versions.json` declares it. Change it
# by ADDING a pack directory and promoting it there, never by editing a released
# one — a decline records the pack that asked, and that pack_version must keep
# resolving to the exact words it recorded.
ACTIVE_PACK = versions.active(_DIR.parent, "persona_pack")

# How a grade finds its sentence in the pack. One reviewed line per word on the
# ladder, in a namespace of its own, said wherever a run states how well a set
# of figures is stood behind. Two sets are stated, so there are two namespaces:
# the answer's own, and a block of rows'. Each names its set in its own words,
# which is what tells a person which figures the word is about when both are in
# front of them.
STOOD_BEHIND_MOMENT = "stood_behind_"
ROWS_STOOD_BEHIND_MOMENT = "rows_stood_behind_"

# ------------------------------------------------------------- the contract
#
# Phrasing key -> the slots its template MAY use, and what each slot IS. These
# are the fields the question queue's deterministic intent supplies — nothing
# else may appear in a template, so a phrasing cannot smuggle a claim into a
# question.
# Slot values arrive RENDERED: the pack places things, it never formats or
# computes them. A money slot takes what `render.money` produced — a value, its
# currency and one locale's conventions — and nothing else.

INTENT_FIELDS: dict[str, dict[str, str]] = {
    "identity":                    {"account_ref": ACCOUNT},
    "reconciliation_gap":          {"account_ref": ACCOUNT,
                                    "opening_date": DATE,
                                    "closing_date": DATE},
    "reconciliation_gap_why":      {"opening_money": MONEY},
    "reconciliation_flagged":      {"account_ref": ACCOUNT},
    # A statement whose period is already posted with a different closing
    # figure. It reconciled; it is held because it would count the period
    # twice, which is a different thing to say than "it didn't add up".
    "reconciliation_reissue":      {"account_ref": ACCOUNT},
    # A document held for review, and the same sentence where the account it
    # belongs to is known. The account slot holds an account; the words around
    # it, preposition included, are the pack's.
    "reconciliation_held":         {"doc_type": DOCUMENT},
    "reconciliation_held_for":     {"doc_type": DOCUMENT,
                                    "account_ref": ACCOUNT},
    "transfer":                    {"date": DATE, "money": MONEY,
                                    "description": MERCHANT},
    "transfer_why":                {"candidates": COUNT},
    "merchant":                    {"example": MERCHANT, "count": COUNT,
                                    "money": MONEY},
    "merchant_peer_note":          {},
    "merchant_why":                {},
    "nature_single":               {"date": DATE, "description": MERCHANT,
                                    "money": MONEY},
    "nature_single_why":           {},
    "nature_group_head":           {"count": COUNT, "example": MERCHANT,
                                    "money": MONEY},
    # What a payment of this kind is: the relationship the counterparty implies,
    # or the label already derived for it.
    "nature_group_meaning":        {"what": CATEGORY},
    "nature_group_compound":       {},
    "nature_group_ask":            {},
    "nature_group_why":            {},
    "nature_group_why_documents":  {"documents": DOCUMENT},
    # What kind of arrangement a counterparty is. The head and the direction
    # are said whatever the evidence; what follows is not. A measured shape
    # states the rhythm the records make; an unmeasured one states what the
    # world does with that kind of business and claims no cadence.
    "rhythm_head":                 {"count": COUNT, "example": MERCHANT,
                                    "money": MONEY},
    "rhythm_direction_out":        {},
    "rhythm_direction_in":         {},
    "rhythm_measured":             {"days": COUNT},
    "rhythm_measured_fixed":       {},
    # Where enough was seen and no spacing held: what the dates showed, put
    # as a finding and asked about, with no cadence and no fallback to the
    # prior.
    "rhythm_irregular":            {},
    "rhythm_irregular_ask":        {},
    "rhythm_why_irregular":        {},
    # The last shape, for a counterparty that is two things at once. Each
    # part states its own count and its own money, so no figure here describes
    # a set larger than the one it was measured over.
    "rhythm_mixture_lead":         {},
    "rhythm_mixture_part_repeating": {"count": COUNT, "money": MONEY},
    "rhythm_mixture_part_varying": {"count": COUNT, "money": MONEY},
    "rhythm_mixture_part_lone":    {"count": COUNT, "money": MONEY},
    "rhythm_mixture_ask":          {},
    "rhythm_why_mixture":          {},
    "rhythm_prior_standing":       {},
    "rhythm_prior_either":         {},
    "rhythm_prior_period_monthly": {},
    "rhythm_prior_period_annual":  {},
    "rhythm_prior_period_either":  {},
    "rhythm_ask":                  {},
    "rhythm_why_measured":         {},
    "rhythm_why_prior":            {},
    "corroboration":               {"name": ACCOUNT, "money": MONEY,
                                    "document": DOCUMENT},
    "corroboration_why":           {},
    "corroboration_why_unreliable": {},
    # What the box a person writes in says before they write, and what stands in
    # its place where nothing said in words can settle the question.
    "free_text_invite":            {},
    "answered_by_document":        {},
    # The expectations engine. One phrasing pair per mechanism;
    # the document name comes from the registry (data), never from the model.
    "expectation_retirement_flow":         {"money": MONEY,
                                            "document": DOCUMENT},
    "expectation_retirement_flow_why":     {},
    "expectation_investment_account":      {"account_name": ACCOUNT,
                                            "document": DOCUMENT},
    "expectation_investment_account_why":  {"money": MONEY},
    "expectation_account_cadence":         {"account_name": ACCOUNT,
                                            "last_date": DATE},
    "expectation_account_cadence_why":     {},
    # The interview. The schema pack supplies the plain question (`asks`), the
    # benefit (`unlocks`) and the label for a kind of account as reviewed data;
    # the persona supplies the manner around them, so a generated schema arrives
    # already speakable. Reviewed prose nests inside reviewed prose — it is
    # never a hole for words nobody reviewed.
    "interview":                           {"name": ACCOUNT, "asks": PROSE},
    "interview_unlocks":                   {"unlocks": PROSE},
    "interview_why":                       {},
    "interview_opens":                     {"name": ACCOUNT,
                                            "kind_label": PROSE},
}

# Moment key -> its slots. Moments are the relationship lines: welcome, return,
# the "I don't know" reassurance, and what Viva says back about a reply she
# could not read.
# The only personal slot is the name, derived deterministically from the
# vault's own account holders, never asked of a model.
MOMENT_FIELDS: dict[str, frozenset] = {
    "welcome_empty":  frozenset({"name_part"}),
    "welcome_back":   frozenset({"name_part"}),
    "reassurance":    frozenset({"name_part"}),
    "not_now_ack":    frozenset({"name_part"}),
    "dont_know_ack":  frozenset({"name_part"}),
    "all_settled":    frozenset({"name_part"}),
    # Asking again. A value that does not survive the deterministic check behind
    # the model is refused in Viva's voice and asked again; the slots carry what
    # the check found, never a guess at what was meant.
    "reply_empty":              frozenset(),
    "reply_unanswered":         frozenset(),
    "reply_unreadable_money":   frozenset({"reason"}),
    # An amount is a value AND a currency. Where the currency stated and the
    # currency the account is held in disagree, there is nothing to compute:
    # this product converts nowhere, so it asks.
    "reply_currency_conflict":  frozenset({"stated", "held"}),
    "reply_unreadable_date":    frozenset({"reason"}),
    "reply_unreadable_rate":    frozenset(),
    "reply_not_in_vocabulary":  frozenset({"alternatives"}),
    "reply_unknown_account":    frozenset(),
    "reply_wrong_kind":         frozenset(),
    "reply_too_long":           frozenset(),
    "reply_not_in_words":       frozenset(),
    "reply_question_closed":    frozenset(),
    # And when the reader itself could not answer. A reader that is DOWN is a
    # different thing from one that answered with something unusable: nothing
    # the person can rephrase reaches a reader that is not there, so only one of
    # these two asks them for anything. The other is reached only after the
    # reader has already been given its one chance to fix its own reply.
    "reply_unreachable":        frozenset(),
    "reply_ask_again":          frozenset(),
    # The ledger will not take a figure the sentence did not carry, however
    # well-formed the reading of it was.
    "reply_figure_not_said":    frozenset(),
    # A yes to "do you have the document?" settles nothing on its own: the
    # document is what settles it.
    "reply_document_awaited":   frozenset(),
    # A movement belongs to at most one transfer, so a pair that was already
    # settled records nothing further — and says so, rather than reading as a
    # reply that could not be understood.
    "reply_already_linked":     frozenset(),
    # What is said when a reply about an action can be read as no outcome
    # word: one that does not say whether it was accepted, a refusal that
    # names no reason, and a reply held for a confirmation, which is transient
    # and does not cross a surface boundary.
    "outcome_unstated":         frozenset(),
    "outcome_unexplained":      frozenset(),
    "outcome_held":             frozenset(),
    # A yes that says a thing exists has not said what it is called, and this
    # product does not name a person's accounts for them. The schema pack's own
    # words for the naming question nest inside Viva's.
    "reply_needs_name":         frozenset({"asks"}),
    # What became of an answer: recorded, or held back because applying it would
    # change which accounts a person holds. What is held back is asked for in
    # words like anything else — a yes or a no — and a reply that is not a yes
    # leaves the ledger as it was and says so.
    "reply_recorded":           frozenset(),
    "reply_needs_confirming":   frozenset(),
    "reply_confirm_asks":       frozenset(),
    "reply_not_confirmed":      frozenset(),
    # What a question wants back, one line per kind of thing a slot holds. A
    # person can see that a yes or a no will do, that an amount is wanted, or
    # which closed list an answer has to land in — the same declaration the
    # inbound check reads, said in words.
    "wants_yes_no":             frozenset(),
    "wants_money":              frozenset(),
    "wants_date":               frozenset(),
    "wants_rate":               frozenset(),
    "wants_choice":             frozenset({"alternatives"}),
    "wants_label":              frozenset(),
    "wants_institution":        frozenset(),
    "wants_link":               frozenset(),
    # A slot that holds several of something: one payment that was genuinely
    # several things at once.
    "wants_several":            frozenset(),
    # And what Viva says about an answer of her own. The term a value the
    # arithmetic could not write exactly is spoken with travels with the figure
    # rather than being asked of whoever writes the sentence, and there is one
    # line for each kind of magnitude, so no kind of number is left with no way
    # of saying it.
    "approx_amount":            frozenset({"amount"}),
    "approx_count":             frozenset({"count"}),
    "approx_rate":              frozenset({"rate"}),
    # A figure the person themselves put into the turn rests on their premise
    # and on no record of theirs, and it is written saying so. A stretch of
    # time they named is not a figure at all, and is not written as one.
    "supposed_amount":          frozenset({"amount"}),
    "supposed_time":            frozenset({"when"}),
    # A hole nothing could fill costs its clause and not the turn, and what is
    # missing is named by its kind rather than left as a silence.
    "answer_gap":               frozenset({"what"}),
    # What a read said its own numbers do not cover, placed by the run for
    # every figure the answer stated. The read's sentence is its own and is
    # never reworded; these are the words that introduce it, so a limit does
    # not arrive reading like another claim.
    "answer_limits":            frozenset({"limits"}),
    # And where a stated figure's claim ends, placed by the run the same way. A
    # grade says how well a number is stood behind and says nothing about how
    # much of the question it answers, so a figure over one account of six says
    # which set it came from rather than leaving the sentence around it to
    # imply the whole. One line per way a set can fall short of what the figure
    # claims to measure.
    "boundary_accounts":           frozenset({"counted", "held"}),
    "boundary_selected_account":   frozenset({"account"}),
    "boundary_selected_category":  frozenset({"category"}),
    "boundary_selected_merchant":  frozenset({"merchant"}),
    "boundary_selected_period":    frozenset({"period"}),
    "boundary_selected_since":     frozenset({"day"}),
    "boundary_selected_until":     frozenset({"day"}),
    # The three slices the vault holds no thing for. Each says what a figure
    # was taken over and offers no name to ask a follow-up with, which is the
    # honest form of a scope the read itself would refuse as a filter.
    "boundary_selected_subcategory": frozenset({"subcategory"}),
    "boundary_selected_tag":         frozenset({"tag"}),
    "boundary_selected_currency":    frozenset({"currency"}),
    "boundary_unmeasured":         frozenset({"account"}),
    # A gap no account can name: a document read and not posted may be about an
    # account that does not exist yet, so it is said as a number of documents.
    "boundary_unposted":           frozenset({"count"}),
    # The same declaration where a figure stands beside the account it is
    # about rather than after a clause about it. The lines above open with a
    # word pointing back at what was just said; a figure on a surface of its
    # own is read under nothing, so it states what it is over and what day it
    # is good for.
    "card_boundary_selected_account": frozenset({"account"}),
    "card_boundary_as_of":            frozenset({"day"}),
    # What is said about an account whose figure was kept back: one line per
    # way a figure can fail to be whole, each naming the account it is about.
    "card_withheld_incomplete":       frozenset({"account"}),
    "card_withheld_in_parts":         frozenset({"account"}),
    "card_withheld_unsayable":        frozenset({"account"}),
    # And the same declaration where the figure stands for the whole picture
    # rather than for one account. What a person reads on the panel counts and
    # names nothing: a total is shown above the accounts it was taken over, so
    # the names are already below it and what is left to say is how many. What
    # says why one account is not in a total does name it, because it is read
    # where somebody went looking for exactly that. How much of what a person
    # holds is counted is a claim about the picture and is said once, over the
    # figures the panel shows, rather than on any one of them. Singular and
    # plural, and all against some, are whole sentences chosen by comparing two
    # integers rather than a frame with a word dropped into it.
    # How far the picture reaches is a claim about the picture and never about
    # a total: at two currencies there are two totals and no third, so a line
    # opening "this total" would name either a figure nothing may compose or
    # one of the two, of which it is false. Three lines rather than two,
    # because a verb agreeing with a count is a word dropped into a frame.
    "picture_accounts_all":               frozenset(),
    # And the same where every account is counted and the read still declares
    # itself short of something. A person reads "every account is counted" as
    # "is this everything", so a completeness claim standing over a read that
    # says it is incomplete is false in the way it is actually read. The
    # sentence carries its own resolution: what else is short of whole is said
    # on a figure, which is a different card and may be one of several, so a
    # line depending on what follows it depends on a layout it cannot see.
    "picture_accounts_all_incomplete":    frozenset(),
    "picture_accounts_one":               frozenset({"held"}),
    "picture_accounts_some":              frozenset({"counted", "held"}),
    "picture_boundary_selected_currency": frozenset({"currency"}),
    "picture_boundary_unmeasured_one":    frozenset(),
    "picture_boundary_unmeasured_many":   frozenset({"count"}),
    "picture_boundary_unposted_one":      frozenset(),
    "picture_boundary_unposted_many":     frozenset({"count"}),
    "picture_as_of":                      frozenset({"date"}),
    "picture_oldest_input":               frozenset({"date"}),
    # What stands where no total could be stood behind at all. A blank where a
    # figure was yesterday says the product is broken, which is less true than
    # saying there is nothing to stand behind today.
    "picture_no_figure":                  frozenset(),
    # And where one currency's total alone is kept back. Silence at the figure
    # is what silence is at the panel: a person shown one number where two
    # belong is not told that a second was withheld, and learns nothing was
    # there.
    "picture_withheld_unsayable":         frozenset({"currency"}),
    # And why one account a person holds is not in a total. Names alone do not
    # discharge what is owed here: a person looking at a card with a number on
    # it that the total does not include needs to know whether anything is
    # theirs to do, and only the reason tells them. One whole line per token of
    # the closed vocabulary the read declares them under, so a token with no
    # line fails the build rather than reaching a person as itself.
    "picture_unmeasured_unobserved":      frozenset({"account"}),
    # A gap that names a remedy and one that has nothing to point at are two
    # different things to be told, so they are two lines. That a remedy exists
    # is asserted rather than hoped for: a boundary refuses to be built where a
    # refused gap names nothing that would settle it, so the clause is true by
    # construction. What would settle it is not placed — half a sentence
    # arriving at runtime from text nobody reviewed is a version that resolves
    # to a frame rather than to the words a person was shown.
    "picture_unmeasured_refused":         frozenset({"account"}),
    # And the same two where the account is beneath no figure at all. An
    # account the read could not place in any currency appears on no card, in
    # no total and in no drawer, so counting it and naming it nowhere is not
    # privacy but concealment: a person cannot verify, act on, or discover
    # something the product recorded and calls nothing. It is named at the
    # panel, which is where beneath-nothing lands.
    "picture_unplaced_unobserved":        frozenset({"account"}),
    "picture_unplaced_refused":           frozenset({"account"}),
    # And what the control that opens a picture figure's evidence is called,
    # and what the panel it opens is headed. One total per currency means one
    # control per currency, and two controls announcing the same words conflate
    # two figures nothing may relate — at the moment a person acts on one of
    # them, and only for the person who cannot see which card it sits on. Both
    # take the slice the figure was cut to, because that is the whole of what
    # tells them apart.
    "picture_evidence_label":             frozenset({"currency"}),
    "picture_evidence_heading":           frozenset({"currency"}),
    # How well a set of figures is stood behind: one whole reviewed line per word
    # on the ladder, chosen by that word, so no sentence anywhere is a frame with
    # a machine's word dropped into it. Not one takes a slot. Each is worded as
    # being about its set and states the weakest in it, so it never claims more
    # than the whole of what it covers.
    #
    # A run states this for an answer, over every money figure the answer stated.
    "stood_behind_verified":     frozenset(),
    "stood_behind_corroborated": frozenset(),
    "stood_behind_unverified":   frozenset(),
    "stood_behind_conflicted":   frozenset(),
    # And above a block of rows, over the one read those lines came from. Those
    # figures are among the answer's, so a person reading both sentences reads
    # one set inside another and never two claims that can disagree. The two
    # families say the same four words of different sets, and each says which
    # set it is about rather than leaving a person to work it out.
    "rows_stood_behind_verified":     frozenset(),
    "rows_stood_behind_corroborated": frozenset(),
    "rows_stood_behind_unverified":   frozenset(),
    "rows_stood_behind_conflicted":   frozenset(),
    # A block of rows: how many lines there are is not knowable when the
    # sentence holding them is authored, so the machine writes every one of them
    # and the model writes no words at any.
    "rows_line":                frozenset({"name", "amount"}),
    "gap_money":                frozenset(),
    "gap_count":                frozenset(),
    "gap_rate":                 frozenset(),
    "gap_date":                 frozenset(),
    "gap_period":               frozenset(),
    "gap_account":              frozenset(),
    "gap_merchant":             frozenset(),
    "gap_category":             frozenset(),
    "gap_document":             frozenset(),
    "gap_rows":                 frozenset(),
    "gap_supposed":             frozenset(),
    # And when there is no answer at all. One reviewed sentence per way a turn
    # can fail, chosen by the machine's own tag: nothing composes a refusal at
    # the moment of refusing, so the words a person hears when Viva has nothing
    # are read before they are ever said, like every other thing she says.
    "refusal_model_unreachable":     frozenset(),
    "refusal_unparseable":           frozenset(),
    "refusal_bad_plan":              frozenset(),
    "refusal_unshaped_answer":       frozenset(),
    "refusal_unshaped_read":         frozenset(),
    "refusal_call_budget_exhausted": frozenset(),
    "refusal_bad_delivery":          frozenset(),
    "refusal_unshaped_binding":      frozenset(),
    "refusal_bad_binding":           frozenset(),
    "refusal_unknown_figure":        frozenset(),
    "refusal_unknown_entity":        frozenset(),
    "refusal_unknown_period":        frozenset(),
    "refusal_unknown_reading":       frozenset(),
    "refusal_unfounded_date":        frozenset(),
    "refusal_unfounded_stipulation": frozenset(),
    "refusal_wrong_kind":            frozenset(),
    "refusal_wrong_quantity":        frozenset(),
    "refusal_wrong_scope":           frozenset(),
    "refusal_wrong_subject":         frozenset(),
    "refusal_nothing_established":   frozenset(),
    "refusal_uncited_figure":        frozenset(),
    # And why the turn had nothing, where a read that stopped can
    # account for it. The verdict above is chosen by the turn's own tag
    # and this is chosen by the read's, so the words a person hears are
    # reviewed before the turn begins either way. Not one of them takes a
    # slot: a read is called with values a caller chose, and a cause that
    # could place one would put a word the person never said in front of
    # them as a fact about their records.
    "diagnosis_too_broad":           frozenset(),
    "diagnosis_filter_unsupported":  frozenset(),
    "diagnosis_unknown_account":     frozenset(),
    "diagnosis_unknown_category":    frozenset(),
    "diagnosis_unknown_tag":         frozenset(),
    "diagnosis_unknown_merchant":    frozenset(),
    "diagnosis_unknown_currency":    frozenset(),
    # What is said about a document the vault has just taken in. Capture and
    # reading are two different things, so the first three tell apart three
    # states a person would otherwise read as one: nothing has been chosen to
    # read it, something could read it and nothing on this path did, and
    # something read it and came back with nothing usable. The last three are
    # what is said where nothing was saved at all — the same file already held,
    # a file past what the window will take, and a file that would not open.
    # The size line places the limit rather than stating it, because the limit
    # is one number the reader owns and a second copy of it would be free to
    # drift away from the one being enforced.
    "documents_saved_no_reader":       frozenset(),
    "documents_saved_unread":          frozenset(),
    "documents_read_yielded_nothing":  frozenset(),
    "documents_already_held":          frozenset(),
    "documents_too_large":             frozenset({"limit"}),
    "documents_cannot_open":           frozenset(),
    # And when the vault answers about a document in a way none of those
    # describes. It names no queue and no next screen: a person who has just
    # added a file is not standing anywhere those words would reach them.
    "documents_outcome_unstated":      frozenset(),
    # What is said about a piece of work a person asked to stop. A job is
    # stopped, not a document, so none of these names a file. The first two
    # are the two places a stop can land — on work that was still running, and
    # on the capture that was doing it — and each says what the vault holds
    # now rather than what the step that did not run would have done. The
    # other two are the ways a stop reaches nothing: work that had already
    # finished, and an identity nothing ever minted. They are told apart
    # because a stop that quietly succeeds against nothing tells a person
    # their work ended when nothing was ever asked.
    "jobs_stopped":                    frozenset(),
    "jobs_stopped_capture":            frozenset(),
    "jobs_already_settled":            frozenset(),
    "jobs_unknown":                    frozenset(),
    # What is said about a whole vault leaving and a whole vault coming back.
    # The two happy lines say what was established rather than what was
    # attempted: a copy written without decrypting anything, and a vault
    # opened and read through — because a restore nobody read is not a
    # restore. The unhappy ones are kept apart by what actually stopped, since
    # a name already taken and a file that would not read back ask a person to
    # do two completely different things next.
    "vault_exported":                  frozenset(),
    "vault_export_exists":             frozenset(),
    "vault_export_incomplete":         frozenset(),
    "vault_export_unwritable":         frozenset(),
    "vault_restored":                  frozenset(),
    "vault_restore_occupied":          frozenset(),
    "vault_restore_unreadable":        frozenset(),
    "vault_restore_unsafe":            frozenset(),
    # What is said about going back over what a vault already holds. The line
    # for a pass that changed nothing is its own rather than an empty list,
    # because a list with no rows and a sweep that found nothing read alike on
    # a screen and mean different things. The rest each name one kind of change
    # and place a count in it. The last says what this pass deliberately does
    # not do: a document nothing has read stays unread, because reading one
    # costs money and asks first.
    "rescan_nothing":                  frozenset(),
    "rescan_gaps":                     frozenset({"count"}),
    "rescan_corroborated":             frozenset({"count"}),
    "rescan_linked":                   frozenset({"count"}),
    "rescan_settled":                  frozenset({"count"}),
    "rescan_open":                     frozenset({"count"}),
    "rescan_unread":                   frozenset(),
    # The outbound record. A vault that has sent nothing gets a line of its
    # own, because an empty list and a screen that failed to load are the same
    # picture. Each phase a model call is recorded under has a line saying what
    # was actually sent on it, and a phase this build has no line for says so
    # rather than being described by the nearest one. The last two are absences
    # the read carries rather than a screen composing them: what this record
    # does not cover, and that nothing outside this machine holds a hash of it.
    "outbound_none":                   frozenset(),
    "outbound_some":                   frozenset(),
    "outbound_scope":                  frozenset(),
    "outbound_phase_classify":         frozenset({"count"}),
    "outbound_phase_extract":          frozenset({"count"}),
    "outbound_phase_speak":            frozenset({"count"}),
    "outbound_phase_unnamed":          frozenset({"count"}),
    "outbound_cost":                   frozenset({"amount"}),
    "outbound_window":                 frozenset({"first", "last"}),
    "outbound_models":                 frozenset({"count"}),
    "outbound_no_anchor":              frozenset(),
}


# ------------------------------------------------------------- the machinery


@lru_cache(maxsize=4)
def load(version: str = ACTIVE_PACK) -> dict:
    """The pack, loaded once. A missing pack is a build error, not a fallback —
    Viva with no voice must fail loudly, not mumble defaults from code."""
    d = _DIR / version
    return {
        "version": version,
        "phrasings": json.loads((d / "phrasings.json").read_text()),
        "moments": json.loads((d / "moments.json").read_text()),
    }


def slots_of(template: str) -> set:
    """The slot names a template references — for the lint test."""
    return {name for _, name, _, _ in string.Formatter().parse(template) if name}


class _Strict(dict):
    def __missing__(self, key):
        raise KeyError(f"phrasing slot {{{key}}} was not supplied — a question "
                       "with a hole where a fact should be is a bluff")


def say(key: str, *, version: str = ACTIVE_PACK, **fields) -> str:
    """Render one phrasing. Strict: a missing slot raises; extra fields are
    ignored (the intent may know more than the phrasing chooses to say); a
    declared slot handed something of the wrong kind raises."""
    _check_types(key, fields)
    return load(version)["phrasings"][key].format_map(_Strict(fields))


def _check_types(key: str, fields: dict) -> None:
    """Every declared field must be the kind of thing it was declared to be, and
    the declaration must be the kind of thing the intent actually supplies.

    Only a type whose renderer exists can be checked, and today that is money:
    what `render.money` produced carries a currency and one locale's
    conventions, and a bare number carries neither. A figure that formatted
    itself somewhere else is refused here rather than reaching a person as the
    only sentence in the product written under a convention nobody declared.

    The check runs both ways, because a contract only one side is held to is
    half a contract: a slot declared as money and handed something else fails,
    and so does a slot handed a rendered amount while declaring it as anything
    other than money."""
    declared = INTENT_FIELDS[key]
    for name, value in fields.items():
        want = RENDERED.get(declared.get(name, ""))
        if want is not None and not isinstance(value, want):
            raise TypeError(
                f"phrasing {key!r} places {name!r} as {declared[name]}, and was "
                f"handed {value!r} — a {declared[name]} slot takes what the one "
                f"renderer produced, never a value formatted elsewhere")
        made = next((t for t, produced in RENDERED.items()
                     if isinstance(value, produced)), "")
        if made and name in declared and declared[name] != made:
            raise TypeError(
                f"phrasing {key!r} declares {name!r} as {declared[name]}, and "
                f"the intent supplies what the {made} renderer wrote — the "
                f"declaration is what a reader of the contract is told this "
                f"slot holds, so it must say {made}")


def moment(key: str, *, version: str = ACTIVE_PACK, **fields) -> str:
    """Render one relationship moment."""
    return load(version)["moments"][key].format_map(_Strict(fields))
