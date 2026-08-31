"""Typed fields that versioned persona templates may place.

Kept separate from pack loading and rendering so the declarative voice
contract can be reviewed without the machinery that consumes it.
"""

from __future__ import annotations

from ..render import (ACCOUNT, CATEGORY, COUNT, DATE, DOCUMENT, MERCHANT,
                      MONEY, PROSE)

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
    "plans_title":                 frozenset(),
    "plans_empty_title":           frozenset(),
    "plans_empty_body":            frozenset(),
    "plans_local_reservation":     frozenset(),
    "plans_goal_headline":         frozenset(),
    "plans_goal_explanation":      frozenset(),
    "plans_status_active":         frozenset(),
    "plans_status_paused":         frozenset(),
    "plans_status_set_aside":      frozenset(),
    "plans_status_complete":       frozenset(),
    "plans_status_ahead":          frozenset(),
    "plans_status_on_track":       frozenset(),
    "plans_status_at_risk":        frozenset(),
    "plans_status_unscheduled":    frozenset(),
    "plans_account_available":     frozenset({"balance", "reserved", "available"}),
    "plans_exclusion_not_depository": frozenset(),
    "plans_exclusion_not_issuer":  frozenset(),
    "plans_exclusion_currency":    frozenset(),
    "plans_exclusion_conflicted":  frozenset(),
    "plans_history_reserved":      frozenset({"amount"}),
    "plans_history_released":      frozenset({"amount"}),
    "plans_history_withheld":      frozenset(),
    "plans_proposal_create":       frozenset({"amount"}),
    "plans_proposal_change_terms": frozenset({"amount"}),
    "plans_proposal_reserve":      frozenset({"amount"}),
    "plans_proposal_release":      frozenset({"amount"}),
    "plans_proposal_pause":        frozenset(),
    "plans_proposal_resume":       frozenset(),
    "plans_proposal_set_aside":    frozenset(),
    "plans_proposal_consequence":  frozenset(),
    "plans_draft_ready":           frozenset(),
    "plans_needs_input":           frozenset(),
    "plans_action_refused":        frozenset(),
    "plans_proposal_held":         frozenset(),
    "plans_action_completed":      frozenset(),
    "plans_action_stale":          frozenset(),
    "plans_action_set_aside":      frozenset(),
    "current_period_step_goal":    frozenset({"subject", "date", "amount", "low", "high"}),
    "current_period_exclusion_goal_unreadable": frozenset(),
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
    "boundary_selected_kind":        frozenset({"kind"}),
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
    # Compact surface proof is selected from structured reasons before any
    # wording. These lines disclose conditions the existing grade and boundary
    # families do not necessarily say: arithmetic rounding, a missing evidence
    # condition, an explicit stale ruling, and mixed measurement dates.
    "proof_inexact":          frozenset(),
    "proof_missing_evidence": frozenset(),
    "proof_stale_boundary":   frozenset(),
    "proof_mixed_vintage":    frozenset(),
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
    "outbound_phase_interpret":        frozenset({"count"}),
    "outbound_phase_speak":            frozenset({"count"}),
    "outbound_phase_unnamed":          frozenset({"count"}),
    "outbound_cost":                   frozenset({"amount"}),
    "outbound_window":                 frozenset({"first", "last"}),
    "outbound_models":                 frozenset({"count"}),
    "outbound_no_anchor":              frozenset(),
    # Configuration. The two proposals are worded apart on purpose: how figures
    # are written sends nothing and says so, while naming a model is the moment
    # bytes become able to leave, and its sentence says exactly what would then
    # be able to go and where the record of it is. Every refusal names what
    # stopped and states that nothing changed and nothing was sent, because a
    # person reading a refusal about sending needs both of those facts.
    "settings_presentation_proposed":  frozenset(),
    "settings_presentation_confirmed": frozenset(),
    "settings_model_proposed":         frozenset(),
    "settings_model_confirmed":        frozenset(),
    "settings_model_keyless_confirmed": frozenset(),
    "settings_model_cleared":          frozenset(),
    "settings_declined":               frozenset(),
    "settings_locale_unknown":         frozenset(),
    "settings_currency_unknown":       frozenset(),
    "settings_adapter_unknown":        frozenset(),
    "settings_model_unnamed":          frozenset(),
    "settings_key_missing":            frozenset(),
    "settings_unwritable":             frozenset(),
    # What is said when a document is actually read, and what it turned out to
    # be worth to the picture. The readings that did not post are kept apart —
    # one that will not reconcile, one starting from a balance nothing here has
    # seen, one whose account is ambiguous, and a pay stub waiting for its
    # deposit are four different things to be told, and none of them is a
    # failure to read: a person told the reading failed would go looking for a
    # better scan of a document that was read perfectly well. The row line
    # places the figure a document attested and the account it attested it on;
    # the last says a document nothing rests on, rather than leaving the row
    # silent about it.
    "documents_posted":                frozenset(),
    "documents_held":                  frozenset(),
    "documents_gap":                   frozenset(),
    "documents_identity":              frozenset(),
    "documents_awaiting":              frozenset(),
    "documents_contributed":           frozenset({"amount", "account", "day"}),
    "documents_contributed_nothing":   frozenset(),
    "documents_snapshot_posted":       frozenset(),
    "documents_snapshot_held":         frozenset(),
    "documents_snapshot_unavailable":  frozenset(),
    "documents_activity_complete":     frozenset(),
    "documents_activity_incomplete":   frozenset(),
    "documents_activity_unavailable":  frozenset(),
    "documents_activity_not_applicable": frozenset(),
    # What a conversation says about itself. Speech cannot carry a receipt: a
    # figure on a screen opens a drawer that opens a document, and a figure
    # spoken aloud opens nothing. So one line says where the evidence is rather
    # than pretending to read it, and one refuses to speak a figure whose text
    # mirror is not in front of the person. The last says that speaking and
    # listening stay on this machine, because sending a voice elsewhere would
    # be a new way for things to leave and nobody has decided that.
    "conversation_unconfigured":       frozenset(),
    "conversation_spoken_citation":    frozenset(),
    "conversation_spoken_withheld":    frozenset(),
    "conversation_voice_local_only":   frozenset(),
    # What is said about what moved. The empty line refuses the reading that an
    # empty list means nothing happened. The scope line says where the rows came
    # from and where direction is read from, since a card purchase prints
    # positive and a person reading a sign would have it backwards. The rest
    # name the states a movement can be in that are not plain spending, each
    # said as what it is rather than as an absence.
    "activity_empty":                  frozenset(),
    "activity_scope":                  frozenset(),
    "activity_transfer":               frozenset(),
    "activity_provisional":            frozenset(),
    "activity_unsettled":              frozenset(),
    "activity_category_recorded":      frozenset({"category"}),
    "activity_category_unchanged":     frozenset({"category"}),
    "activity_tags_recorded":          frozenset({"count"}),
    "activity_tags_unchanged":         frozenset(),
    "activity_movement_stale":         frozenset(),
    "activity_correction_refused":     frozenset(),
    "activity_tags_scope_refused":     frozenset(),
    "activity_transfer_suggested":     frozenset({"count"}),
    "activity_transfer_suggestion_incomplete": frozenset({"count"}),
    "activity_transfer_relationship":  frozenset({
        "source_date", "source_description", "source_account", "source_amount",
        "counterpart_date", "counterpart_description", "counterpart_account",
        "counterpart_amount",
    }),
    "activity_transfer_linked_human":  frozenset(),
    "activity_transfer_linked_evidence": frozenset(),
    "activity_transfer_confirmed":     frozenset(),
    "activity_transfer_rejected":      frozenset(),
    "activity_transfer_unlinked":      frozenset(),
    "activity_transfer_state_stale":   frozenset(),
    # What is said when a person names a folder. These are kept apart because
    # they ask for completely different next steps: a folder holding no vault,
    # a path that is not a folder at all, a vault this passphrase will not
    # open, and a vault made on purpose. A mistyped path used to answer as an
    # opened, brand-new empty vault, which reads to a person as their records
    # having vanished.
    "vault_absent":                    frozenset(),
    "vault_not_a_folder":              frozenset(),
    "vault_wrong_passphrase":          frozenset(),
    "vault_created":                   frozenset(),
    "vault_opened":                    frozenset(),
    # What Trust says about the rest of itself. The anchoring line is the
    # plainest sentence in the pack on purpose: an absent capability described
    # in soft words reads as a capability, and this one is the difference
    # between a person checking a claim and taking it. The maintenance lines
    # keep a plan apart from a run, because a report of what would happen and a
    # report of what did are the same shape on a screen. The diagnostic line
    # says what the file holds rather than promising what it leaves out.
    "maintenance_planned":             frozenset(),
    "maintenance_started":             frozenset(),
    "maintenance_ran":                 frozenset(),
    "maintenance_unconfigured":        frozenset(),
    "trust_no_anchoring":              frozenset(),
    "trust_no_maintenance_yet":        frozenset(),
    "trust_no_conversation_history":   frozenset(),
    "diagnostic_written":              frozenset(),
    "diagnostic_unwritable":           frozenset(),

    # The sample vault, and the frame around it. One frame said once and
    # permanently, rather than a qualifier on every sentence: a qualifier on
    # one figure quietly claims the unqualified figures beside it are
    # different, and a person evaluating this product ends up reading our
    # disclaimers instead of the picture we say we can draw.
    "vault_sample_opened":             frozenset(),
    "sample_frame":                    frozenset(),
    "sample_frame_detail":             frozenset(),
    "sample_frame_leave":              frozenset(),
    "sample_vault_unopened":           frozenset(),

    # What happens to this application when a new version of it exists, and
    # what happens to a person's records when it does. Nothing here checks for
    # an update or installs one; these say that plainly rather than leaving a
    # screen to imply a channel by having a section about one.
    "update_no_channel":               frozenset(),
    "update_vault_untouched":          frozenset(),
    "update_recovery":                 frozenset(),
    "update_installed_build":          frozenset(),
    "update_source_build":             frozenset(),
    "update_unknown_build":            frozenset(),
    # Grounded obligations and deterministic findings. Every fact-bearing slot
    # comes from the projection; the pack only decides how that fact is said.
    "obligation_due":                   frozenset({"subject", "date"}),
    "obligation_expected":              frozenset({"subject", "date"}),
    "obligation_amount_exact":          frozenset({"amount"}),
    "obligation_amount_range":          frozenset({"low", "high"}),
    "obligation_coverage":              frozenset({"count", "first", "last"}),
    "obligation_measured_caveat":       frozenset(),
    "obligation_observed_caveat":       frozenset(),
    "finding_possible_duplicate_headline": frozenset({"subject"}),
    "finding_possible_duplicate_explanation": frozenset(),
    "finding_amount_changed_headline":  frozenset({"subject"}),
    "finding_amount_changed_explanation": frozenset({"prior", "current"}),
    "finding_expected_outflow_missing_headline": frozenset({"subject"}),
    "finding_expected_outflow_missing_explanation": frozenset({"date"}),
    "finding_income_interrupted_headline": frozenset({"subject"}),
    "finding_income_interrupted_explanation": frozenset({"date"}),
    "finding_fee_observed_headline":    frozenset({"subject"}),
    "finding_fee_observed_explanation": frozenset(),
    "finding_recurring_obligation_headline": frozenset({"subject"}),
    "finding_recurring_obligation_explanation": frozenset(),
    "finding_coverage":                 frozenset({"count", "last"}),
    "finding_set_aside":                frozenset(),
    "finding_stale":                    frozenset(),
    # Current-period control. The projection owns every amount and boundary;
    # these moments only turn the closed result into reviewed interface copy.
    "current_period_title":             frozenset(),
    "current_period_kicker":            frozenset(),
    "current_period_headline":          frozenset({"date", "low", "high"}),
    "current_period_headline_exact":    frozenset({"date", "amount"}),
    "current_period_explanation":       frozenset(),
    "current_period_coverage_one_one":  frozenset({"accounts", "steps"}),
    "current_period_coverage_one_many": frozenset({"accounts", "steps"}),
    "current_period_coverage_many_one": frozenset({"accounts", "steps"}),
    "current_period_coverage_many_many": frozenset({"accounts", "steps"}),
    "current_period_missing_plans":     frozenset(),
    "current_period_old_balance":       frozenset(),
    "current_period_undated_balance":   frozenset(),
    "current_period_conflicted_balance": frozenset(),
    "current_period_income_interrupted": frozenset(),
    "current_period_exclusion_not_depository": frozenset(),
    "current_period_exclusion_not_issuer": frozenset(),
    "current_period_exclusion_currency_unstated": frozenset(),
    "current_period_exclusion_income_unqualified": frozenset(),
    "current_period_exclusion_obligation_unqualified": frozenset(),
    "current_period_bounded_range":    frozenset(),
    "current_period_evidence_label":   frozenset({"currency"}),
    "current_period_evidence_heading": frozenset({"currency"}),
    "current_period_assumption_horizon": frozenset(),
    "current_period_assumption_income": frozenset(),
    "current_period_assumption_recurring": frozenset(),
    "current_period_refused":           frozenset(),
    "current_period_step_balance":      frozenset({"date", "amount"}),
    "current_period_step_income":       frozenset({"subject", "amount", "date", "low", "high"}),
    "current_period_step_obligation":   frozenset({"subject", "amount", "date", "low", "high"}),
}
