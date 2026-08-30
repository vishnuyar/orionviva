# The Conduit and the Counterparty — reading a descriptor as a record

**State:** built
**Rules:** MER-1, MER-2, MER-3, MER-4, MER-5, MER-6, MER-7, MER-8, MER-9, MER-10, MER-11, MER-71, MER-12, MER-13, MER-14, MER-15, MER-16, MER-17, MER-18, MER-19, MER-70, MER-72

## Rules

### MER-1 — The slot vocabulary is closed
**State:** enforced
**Code:** merchant/merchantcore/profile.py:42 (`SLOTS`), :181 (`Template.compile`), merchant/merchantcore/induce.py:96 (`vocabulary_block`)
**Test:** merchant/tests/test_profile.py::test_only_names_from_the_vocabulary_compile, merchant/tests/test_profile.py::test_the_prompt_is_rendered_from_the_same_dict_the_validator_enforces

1. A template names holes only from `SLOTS`; any other name raises `ProfileError`.
2. A template carries no regular expression; the expression is compiled from the template in this package.
3. A slot other than `noise` appears at most once in one template.
4. The prompt's slot list is rendered from `SLOTS`, so prompt and validator cannot name different sets.

### MER-2 — A template explains a whole line or none of it
**State:** enforced
**Code:** merchant/merchantcore/profile.py:209 (anchored at both ends), :277 (`Profile.apply`)
**Test:** merchant/tests/test_profile.py::test_a_match_explains_the_whole_line

1. A compiled template is anchored at both ends, so every character of a matched descriptor lands in a slot or a literal.
2. `apply` returns the first template that matches; template order is part of the grammar.
3. No match is a legitimate answer and returns `None`.

### MER-3 — Privacy is a slot name
**State:** enforced
**Code:** merchant/merchantcore/profile.py:64 (`PERSONAL_SLOTS`), :70 (`PARTY_SLOTS`), :212 (`party_slot`), :239 (`Match.personal`), :243 (`Match.shareable`)
**Test:** merchant/tests/test_profile.py::test_personal_and_shareable_are_decided_by_slot_not_by_text, merchant/tests/test_profile.py::test_a_contact_where_the_party_belongs_is_personal_by_STRUCTURE

1. `counterparty`, `counterparty_handle` and `account_ref` are personal by declaration; nothing inspects the text that landed in them.
2. A template naming no party slot promotes its `{contact}` to personal, because a line that names nobody prints a person's contact detail rather than a shop's.
3. `{institution}` never counts as naming the other side; it names the conduit the money crossed.
4. `noise` is carried and never shared.

### MER-4 — A wire is refused every layer
**State:** enforced
**Code:** merchant/merchantcore/descriptor.py:54 (`_WIRE_MARKERS`), :78 (`is_never_templatable`), merchant/merchantcore/profile.py:284, merchant/merchantcore/resolve.py:262
**Test:** merchant/tests/test_profile.py::test_a_wire_is_refused_a_grammar_however_good_the_template_looks, merchant/tests/test_profile.py::test_a_refused_line_is_excluded_from_coverage_not_counted_against_it

1. A line carrying two or more distinct Fedwire/SWIFT markers is refused a grammar; no template may claim it.
2. The refusal is checked before any template is tried, not after.
3. Refused lines are excluded from the coverage denominator rather than counted against a grammar.

### MER-5 — A slotless template needs a line the bank repeats
**State:** enforced
**Code:** merchant/merchantcore/profile.py:349 (`validate_evidence`), merchant/merchantcore/induce.py:274 (`_fixed_phrase`)
**Test:** merchant/tests/test_profile.py::test_a_template_with_no_holes_is_an_example_not_a_grammar, merchant/tests/test_profile.py::test_a_fee_line_is_a_grammar_when_the_bank_prints_it_repeatedly

1. A template with no holes is kept only where some line it matches occurs more than once in the corpus.
2. Without counts, every slotless template is refused.
3. `validate` (format only) admits a frozen slotless template at load time; the evidence rule lives only in `validate_evidence`.

### MER-6 — A profile is a versioned pack, never edited
**State:** enforced
**Code:** merchant/merchantcore/profile.py:375 (`ProfileStore`), :481 (overwrite refusal), :470 (coverage comparison)
**Test:** merchant/tests/test_profile.py::test_a_released_profile_cannot_be_overwritten, merchant/tests/test_profile.py::test_a_worse_rerun_cannot_silently_become_the_grammar

1. The filename is the version; `write` refuses to overwrite an existing profile id (T7).
2. Where evidence is supplied, a new version that explains a smaller share of those movements than the version it succeeds is refused unless `force` is passed.
3. `latest` resolves by version number, so a superseded version keeps resolving for the records stamped with it.

### MER-7 — A grammar is gated and chosen on lines it never saw
**State:** enforced
**Code:** merchant/merchantcore/induce.py:70 (`holdout_split`), :352 (`Induction.scored`), :359 (`accepted`), :426
**Test:** merchant/tests/test_profile.py::test_a_grammar_is_gated_on_lines_that_never_helped_choose_it, merchant/tests/test_profile.py::test_the_holdout_is_stable_so_two_runs_measure_the_same_thing

1. A share of distinct lines is withheld before induction begins: never sampled, never used to choose between candidates.
2. The gate and any selection between candidate grammars read the held-out score where one exists, the training coverage only where there is no holdout; the check is deterministic, with no model in the loop (T2).
3. The split is a hash of the descriptor salted with `PROFILE_FORMAT`, so two runs over one vault split identically and a descriptor keeps its side as the vault grows.
4. Coverage is measured over every eligible descriptor, weighted by movements, never over the sample.

### MER-8 — The induction thresholds
**State:** enforced-with-exception
**Code:** merchant/merchantcore/induce.py:50 (`DEFAULT_SAMPLE` 40), :53 (`MIN_COVERAGE` 0.80), :57 (`MAX_ROUNDS` 3), :62 (`HOLDOUT_SHARE` 0.20), :67 (`MIN_LINES_TO_INDUCE` 30)
**Test:** merchant/tests/test_profile.py::test_a_grammar_that_explains_the_rare_lines_and_misses_the_mass_fails, merchant/tests/test_profile.py::test_the_loop_shows_each_round_only_what_the_last_one_missed

1. A pair with fewer than 30 distinct lines is not induced; it still resolves through Layer 0 and the normalizer.
2. A grammar scoring below 0.80 is not accepted and not written.
3. Induction is a loop bounded at three rounds; each round sees only what the accumulated grammar could not explain, and stops early when a round returns nothing new or explains no new line.
4. At most five examples of any one line shape ride in a sample, chosen for difference from each other rather than frequency.

**Exception:** `MIN_LINES_TO_INDUCE` is a constant `Inducer.induce` never reads (merchant/merchantcore/induce.py:410). Assertion 1 is enforced by two callers — product/viva/induce_profile.py:262, which `--force` bypasses, and product/viva/agent/act.py:90 — and by neither cited test. Nothing in the package refuses a three-line induction.

### MER-9 — The layer order, and a borrowed grammar
**State:** enforced
**Code:** merchant/merchantcore/resolve.py:42 (`LAYERS`), :50 (`Resolution.layer`), :234 (`resolve_descriptor`), :274 (borrowing)
**Test:** merchant/tests/test_merchantcore.py::test_the_banks_own_grammar_always_wins, merchant/tests/test_merchantcore.py::test_which_lender_wins_does_not_depend_on_dict_order, merchant/tests/test_merchantcore.py::test_a_borrowed_grammar_is_still_a_grammar, merchant/tests/test_merchantcore.py::test_borrowing_never_reaches_a_refused_line

1. Layers are applied refused → the bank's own grammar → a borrowed grammar → published rules → the normalizer, each claiming only what it can prove, and the resolution records which layer produced it (T1).
2. The bank's own grammar always wins over a borrowed one.
3. Borrowed grammars are tried in profile-id order, so the answer never depends on iteration order; where one matches, `borrowed_from` records it.
4. A borrowed match is recorded as layer `grammar`, because downstream privacy checks key on that word.

### MER-10 — Identity is brand-level
**State:** enforced
**Code:** merchant/merchantcore/resolve.py (`Resolution.identity_candidates`), merchant/merchantcore/catalog.py (`resolve`), product/viva/ledger/projection/merchants.py (`merchant_keys_of`)
**Test:** merchant/tests/test_merchantcore.py::test_store_number_boundaries_offer_exact_identity_candidates, product/tests/test_merchant_keys.py::test_reviewed_aliases_group_two_location_forms_under_one_merchant, ::test_reviewed_aliases_do_not_match_a_near_name_or_arbitrary_text

1. A grammar or published parser may name a normalized brand. Where a proven occurrence slot such as a store number supplies a boundary, its exact left-hand prefix is also a candidate; location after the boundary remains occurrence context.
2. A versioned catalog may map one of those candidates to a permanent merchant id only through an exact reviewed alias. No substring, fuzzy score, city list, or model-authored display name establishes identity.
3. Where no layer or reviewed alias identifies the merchant, the key falls back to the whole normalized line, which still carries whoever was on it — never to the institution. Unknown remains unknown.
4. Refused and person-declared lines never consult business aliases. Context travels with a hint only where every occurrence of the merchant agreed on it.

### MER-11 — A rail is proven by structure, never by a word
**State:** enforced
**Code:** merchant/merchantcore/resolve.py:139 (`_DE43_RULES`), :164 (`channel_of`), :143 (`rail_of`), product/viva/ledger/streams.py:450-478
**Test:** product/tests/test_streams.py::test_a_merchant_with_one_proven_channel_does_not_split_across_templates, product/tests/test_streams.py::test_an_atm_withdrawal_and_a_cheque_still_separate

1. A channel is claimed only where a published format proves it — a NACHA tail, two wire tags, an ISO 8583 DE43 structure — or where a grammar put a person in a slot named for one; otherwise it is `unknown` and stays `unknown` (X2).
2. No rule keys a channel on a word in the descriptor text.
3. Where this line proves nothing, the rail falls back to the channel the same counterparty's other lines prove when they prove exactly one, and that inference is bounded to one account at one institution.
4. Failing both, the template stands in for the rail, so two lines off one template stay one stream.

### MER-71 — A brand slot crosses only where a published format corroborates the line
**State:** enforced-with-exception
**Code:** merchant/merchantcore/resolve.py:180 (`corroborates_a_business`), product/viva/ledger/hints.py:128, :160 (`_named_by_a_slot`)
**Test:** product/tests/test_hints.py::test_a_brand_a_grammar_named_crosses_only_where_a_published_format_agrees, product/tests/test_hints.py::test_a_format_one_line_proves_does_not_certify_its_sibling, product/tests/test_hints.py::test_one_uncorroborated_stream_withholds_the_hint_it_shares, product/tests/test_hints.py::test_the_gate_does_not_wait_for_a_grammar_that_names_a_person

1. A slot name may say a hole holds a person; it may not, by itself, say a hole holds a business. This is the mechanism **T9** names; T9 is the invariant and this rule is how it is honoured at the descriptor edge.
2. Where a grammar named the brand, the hint crosses only if a published format read from each line behind it says the other side was a business.
3. Corroboration is never inherited: a format a sibling line proved certifies nothing.
4. The unit withheld is the whole hint — brand and context together — because a party's name lands in whichever slot the model called impersonal.
5. The gate applies to every grammar, including one that names no person anywhere.
6. Nothing about local resolution moves: the stream still keys on the brand, the merchant key still forms, categorization still works.

**Exception:** the ACH clause is satisfied by a Company Name that `split_ach_heads` recovered from the corpus rather than read from a published boundary on the line (merchant/merchantcore/descriptor.py:285, merchant/merchantcore/resolve.py:200). An ACH line whose head is a person's given name is therefore corroborated and crosses. Recorded in the test that names it: product/tests/test_hints.py::test_an_ach_line_whose_head_recovered_a_company_name_corroborates.

### MER-12 — The declaration travels with the keys
**State:** enforced
**Code:** product/viva/ledger/merchant_keys.py:32 (`MerchantKeys`), :48 (`resolve_keys`), product/viva/ledger/projection/merchants.py:28 (`merchant_key_map`), :84 (`is_person`), product/viva/ledger/projection/rhythm.py:242
**Test:** product/tests/test_merchant_keys.py::test_a_resolver_declaring_nothing_is_told_apart_from_one_of_the_wrong_shape, product/tests/test_rhythm.py::test_a_person_shaped_stream_reaches_no_prompt_no_catalog_and_no_question

1. A resolver returns the line-to-key mapping and the lines a grammar slot declared a party on; it is the same declaration the enrichment gate reads, never a second way of asking.
2. A resolver returning any other mapping raises `TypeError` rather than defaulting to silence.
3. The rhythm read drops a declared person's movements before any flow is formed, so a person contributes no hypothesis, no question and no subject a ruling could be recorded under.
4. A projection built with no resolver declares nobody and normalizes each descriptor to itself.

### MER-13 — `is_shareable` answers only where no grammar does
**State:** enforced
**Code:** merchant/merchantcore/normalize.py:68 (`is_shareable`), product/viva/ledger/hints.py:118
**Test:** product/tests/test_hints.py::test_with_no_grammar_the_conservative_list_still_guards_a_peer_payment, merchant/tests/test_merchantcore.py::test_a_line_the_english_list_cannot_read_is_not_cleared_by_its_silence

1. Where a stream's layer is not `grammar`, every occurrence's descriptor must pass `is_shareable` for the stream to cross.
2. `is_shareable` fails closed: a peer-payment marker, any alphabetic character outside ASCII, or nothing left after normalization all refuse.
3. Silence from the marker list is not a clearance for a line the list cannot read.
4. Inducing a grammar for an institution retires the list there.

### MER-14 — A kind that names no party gets neither a grammar nor enrichment
**State:** enforced
**Code:** merchant/merchantcore/profile.py:75 (`INDUCIBLE_KINDS`), :78 (`is_inducible`), :442 (`latest_for`), :463, product/viva/ingest/categorize.py:229
**Test:** merchant/tests/test_profile.py::test_a_kind_whose_lines_name_no_party_gets_no_grammar, merchant/tests/test_profile.py::test_a_grammar_is_never_served_for_an_ineligible_kind, product/tests/test_merchant_enrich.py::test_only_accounts_whose_lines_name_a_party_are_enriched

1. `INDUCIBLE_KINDS` is an allowlist of account kinds whose descriptors name a party.
2. A kind outside it may not have a grammar induced, is never served one however many files exist, and its merchants are never offered for enrichment.
3. The gate reads the account kind the ledger already holds, never anything about the text.

### MER-15 — A better layer must not return less than a worse one
**State:** enforced
**Code:** merchant/merchantcore/resolve.py:227 (`_slot_from` re-adds `entry_description`), :292
**Test:** product/tests/test_streams.py::test_the_ach_entry_description_is_recovered_from_the_statement

1. A grammar match that absorbed the NACHA Company Entry Description into literal text still reports it, recovered from the statement-level split.
2. A higher layer displacing a lower one may not drop a field the lower one proved.

### MER-16 — Word-recurrence counts decide nothing
**State:** enforced
**Code:** merchant/merchantcore/descriptor.py:245 (`word_owners`)
**Test:** product/tests/test_streams.py::test_word_recurrence_is_a_diagnostic_and_decides_nothing

1. `word_owners` is a diagnostic for the streams report only.
2. No rule may key on how many normalized keys print a word.

### MER-17 — The shape set is kept small on purpose
**State:** enforced
**Code:** merchant/merchantcore/profile.py:109 (`SHAPES`), :123 (`merchant` shape, no `#`), :143 (`SLOT_SHAPE`), :89 (`_MARKS`)
**Test:** merchant/tests/test_profile.py::test_a_hash_is_left_out_because_it_slots_wrongly, merchant/tests/test_profile.py::test_a_name_may_not_start_with_a_digit_and_a_merchant_string_may

1. `#` is not in any shape; a template writes it as literal text with `{store_number}` after it.
2. `counterparty` stays on the narrow `words` shape and is never widened.
3. A name shape starts with a letter; only `brand` and `noise` take the wider `merchant` shape, which may start with a digit.
4. Combining marks are enumerated by codepoint range, because this package takes no third-party regex dependency.

### MER-18 — The induction diagnostics decide nothing
**State:** enforced
**Code:** merchant/merchantcore/induce.py:159 (`narrow_templates`), :179 (`uncorroborated_brands`), product/viva/induce_profile.py:341-361
**Test:** merchant/tests/test_profile.py::test_a_template_is_judged_by_what_it_MATCHES_not_by_its_words, merchant/tests/test_profile.py::test_a_brand_slot_is_counted_against_the_lines_that_prove_nothing

1. `narrow_templates` reports every template matching one distinct line or none, measured by matching rather than by inspecting literal words.
2. `uncorroborated_brands` reports, per template, how many distinct lines put a party in a brand slot with nothing published agreeing.
3. Both are printed beside a fresh grammar for a person to read; neither gates anything, and neither reaches a grammar already in force.
4. Their counts are distinct lines, not a measure of what the enrichment boundary withholds.

### MER-19 — A non-English peer line still crosses where no grammar exists
**State:** unmet
**Code:** merchant/merchantcore/normalize.py:68 — `is_shareable("PAGO A JUAN")` and `is_shareable("VIREMENT A MARIE")` both return True, so both are offered for enrichment where the institution has no grammar
**Test:** none

1. A peer payment named in a language the marker list does not speak must not cross the enrichment boundary, with no Spanish or French in the codebase (I2).
2. The non-ASCII clause catches accented spellings only; an ASCII non-English line passes.

### MER-70 — A slot empty across a whole statement means the grammar is wrong
**State:** unmet
**Code:** none found — nothing in merchant/merchantcore/induce.py or merchant/merchantcore/profile.py inspects whether a named slot ever captured a value
**Test:** none

1. A slot that stays empty across every line of the statement a grammar was induced from means the grammar is wrong, not merely incomplete.
2. Nothing checks this; the gates read whether a template *matched*, never what landed in its holes.

### MER-72 — No token from an occurrence attribute reaches the commons, and a test says so
**State:** unmet
**Code:** merchant/merchantcore/catalog.py:161 (`export` returns record fields only, for keys `is_shareable` passes), :187 (`_save`), merchant/merchantcore/enrich.py:143-155 (a record's attributes are built from a closed set of reply keys, so no occurrence attribute has a path in), product/viva/ingest/categorize.py:298 (`export_catalog` returns `{category, grade}`)
**Test:** none walks the export for occurrence attributes — merchant/tests/test_merchantcore.py:99 (`test_catalog_pending_add_and_linted_export`) reads `Catalog.export()` only to assert a peer key is filtered and a record reloads, and product/tests/test_merchants.py:114 (`test_export_catalog_is_linted_and_carries_no_amounts`) asserts the key set of one record from the product's own `export_catalog`

1. No token from any occurrence attribute can reach the commons — publication is a schema and not a decision, so occurrence attributes are unreachable rather than filtered.
2. That is enforced by a test that walks the export, not by review. No such test exists.

## Why

A descriptor is not free text. It is the flattened tail of a pipeline that
carried typed, fixed-width fields, and the person is not hiding in ambiguous
prose — the person is in a known slot of a known format. ISO 8583 DE43 is
positional: merchant name, then city, then a state or country code, with an
asterisk at a specified index separating a brand prefix from a sub-merchant, and
a card-absent transaction legally putting a phone number or URL in the
thirteen-character city slot. NACHA record layouts are fixed-width, so the
platform, the purpose token and the person are three separate fields. Zelle runs
over RTP, which is native ISO 20022, so a Zelle sentence is something the *bank
composed* for display out of data that was already typed. Europe never had the
problem at all: `camt.053` carries structured creditor names and a three-level
taxonomy, and Mastercard already mandates enhanced merchant data there. So the
target is not a cleaned string but a record with provenance on every field, and
the durable move is to build the consumer of structured data and let parsing be
the fallback.

That reframing is what replaced the substring list. The old gate answered, with
ten English substrings filed under privacy rather than classification, the very
question enrichment exists to answer — *is this a peer payment?* — and it failed
in both directions: every English descriptor containing "to" was excluded, every
non-English one carrying a name was admitted. Worse, one function decided eight
different things, some asking *may this leave the machine?* and some asking *does
this describe a pattern?*, which is why a ruling about a savings transfer refused
to generalize. The replacement is not a better list but a different kind of
thing: the slot a value came from already said whether it may travel.

The layers each shrink what the next one sees. Layer 0 is network-universal and
deterministic — it needs no model and no profile, and it cannot claim the brand,
because no published rule says where a brand ends. Layer 1 is an induced grammar
keyed by (institution × rail × document type), because a checking line and a card
line from one bank have unrelated grammars. Layer 2 is the merchant knowledge
base, reached only on a miss, and by then the input is a short clean brand
string — which is the input on which the only public benchmark separates 0.87 for
a knowledge-base-backed system from 0.66 for naive frontier-model normalization.
Better privacy and better accuracy turn out to be the same change.

A profile is never obtained by asking a model how a bank encodes its descriptors.
That is a recall question about undocumented, drifting, per-bank behaviour that
no model was trained on, and it will be answered fluently anyway. It is obtained
by showing the model real descriptors from the statement in hand and asking what
grammar produced them: the model perceives what is in front of it and is never
believed about the world. The same distinction the whole extraction path rests
on.

Which lines to show is a solved problem elsewhere. Log template mining has a
decade of parsers and a public benchmark, and two of its results transfer
directly. Mask the variable parts *before* grouping — [*Preprocessing is All You
Need*](https://arxiv.org/html/2412.05254v1) measures moving masking ahead of
grouping as a 109% rise in Drain's template-accuracy F1 and 48% in its grouping
F1 — because grouping on the raw line turns twenty-one lines differing only in a
posting date into twenty-one groups. And within a group show lines that are
*unlike* each other: [LogBatcher](https://arxiv.org/html/2406.06156v2) measures
similarity-based selection at 7.7% worse than diversity-maximizing selection, and
[DivLog](https://arxiv.org/pdf/2307.09950) finds that replacing diverse sampling
with random costs 11% parsing accuracy and 28% template precision. A model learns
where a hole is by seeing one template with different fillers; three
near-identical lines teach it nothing about which part varies. Batch size
transfers too — five to ten lines, with larger batches slightly worse.

The vocabulary is used twice, and that is what makes it worth having: it is
rendered into the prompt and it is enforced by the validator, so the two cannot
drift apart. Two properties then fall out of the structure rather than being
checked afterwards. Losslessness is structural, because the compiled expression
is anchored at both ends, so there is no partial parse to mistake for a complete
one. And privacy is a slot name, declared in code rather than inspected in text.

What a slot name cannot protect is a field whose contents are unconstrained. A
wire is a Fedwire or SWIFT message dumped into a display line, carrying an
operator free-text field holding whatever the sender typed — a street address on
a property purchase, anything at all on a family transfer. No slot name can
honour that, so the wire shape is refused a grammar outright rather than parsed
carefully, and the refusal is checked before templates are consulted, or it would
only be as strong as the templates that happen to exist today.

One thing the model writes is bounded by nothing above: the literal text between
the holes. A template could bake a person's name into its literals and carry it
into a file whose entire premise is that it is impersonal. The tempting rule —
*a word occurring in exactly one descriptor is not a literal* — was rejected in
the building, because a genuine bank literal such as the NACHA entry description
`Payroll` may occur under one originator on one statement. What exists instead
counts how many distinct lines each template matches: a name baked into literal
text lands there, because a template carrying it can only ever match its own
line. It is an advisory printed beside the grammar, not a gate, and a name baked
into a template that still matches several lines is invisible to it. Reading
remains the line of defence, and it is the one people skip.

A profile is a data pack for the strongest reason of the four packs this project
keeps — it is applied to *every line a bank ever prints*, so a template accepted
and then quietly corrected would mean two different meanings share one id, and
every record stamped with that id becomes unreadable.

The lossless-parse check earns three things at once. It is a gate, because a
profile that mis-slots a field is wrong consistently and confidently for every
transaction from that institution, which is worse than one bad read. It is a
loop, because a bank's long tail is a *different set of templates* rather than a
vaguer version of the common ones — capped, because the tail is finite but
one-off lines are not. And it is a drift detector for free: the number that gated
the profile keeps being computed on every ingest, and a drop is the signal. The
recent figure moves first; lifetime coverage barely twitches when a bank adds a
shape, because old lines outnumber new. A grammar at 84% lifetime and 40% on the
last quarter stopped working three months ago, and only one of those figures says
so. Because profiles are versioned and never edited, the response is a new
version with the old one still resolving — drift becomes an ordinary version bump
instead of a silent, retroactive change of meaning. It also makes a *shared*
profile safe in a way the merchant catalog is not: a recipient can verify someone
else's grammar against their own statement before trusting it.

Identity is brand-level because the whole field converged there independently —
Plaid, Spade, MX, Stripe Issuing and Heron all pair a brand-level identifier
stable across locations with a separate location identifier. OrionViva now makes
that separation only where structure or an exact reviewed alias supports it. Two
hundred stores can produce one commons row; an unsupported descriptor remains a
separate honest unknown rather than being fuzzily forced into that row.

Three boundaries, not one. The whole descriptor crosses to the induction model
call, and it may, because ingest already sent every page of the statement
including that line. The whole record, counterparty included, crosses into the
encrypted local store. Only the merchant block and the grammar profile cross to
the commons, and publication is a schema rather than a decision: occurrence
attributes have no path to the export.

Then the asymmetry that the corroboration gate exists for. Believing
`{counterparty}` costs enrichment coverage and never a name, so it is believed.
`{brand}` is the claim that goes the other way, and it was believed on a model's
word alone. Gating it costs coverage — the errors this gate makes all have one
shape, a genuine business on a rail that proves nothing losing its enrichment —
and that asymmetry is the reason to accept the price. It is stated as the weaker
true sentence rather than the stronger false one: the crossing is gated, and the
gate's evidence includes one signal inferred from the corpus. A fence believed to
close something it does not is worse than no fence.

Several parts of this design were falsified by real data and are kept as
reasoning rather than as rules. **Token fan-out as the privacy gate** — a token
may cross only if it heads *K* distinct descriptors — was falsified the day it was
proposed: 116 heads led exactly one key, so ordinary single-location merchants
would all have been blocked; the rule admitted bare month numbers as shared
knowledge; and `the` heads three keys, so head-keying merges unrelated retailers.
188 heads is too coarse and 492 keys too fine — neither is a merchant. The deeper
error was that it was a statistical re-implementation of the reflex this codebase
keeps catching: computing locally a piece of world knowledge that could simply be
asked for. **Stripping "the bank's own words" from a brand candidate** by counting
how many counterparties print each word was falsified the same way: the ranking
interleaves three populations — bank sentence words, city names, merchant names —
so no threshold separates them, and the count was circular besides, because
normalization fragments one merchant into many, so a merchant with fifteen
spellings looks like fifteen counterparties agreeing. Separating the bank's
sentence from the merchant's name is Layer 1's job, done from evidence with a
lossless check. **A keyword table nearly went back in at the centre**, deriving
the channel by matching English phrases against the text; it now comes from
structure only, and the ATM and cheque distinctions were lost and recovered for
free, because two lines matching one template came off one rail by construction.

Some rulings live in the code and were argued nowhere else. An investment line is
refused a grammar because every name in the vocabulary asserts something about a
party or a place, and an activity line describes a trade against a security and
holds no party at all; a grammar induced over such lines would file a realized
gain as `{purpose}` and a security as `{brand}`, consistently, on every line that
institution prints — a confident wrong answer manufactured at scale. Instrument
events need their own vocabulary, which belongs to a deferred `instrumentcore`.
`#` is kept out of the shapes because admitting it lets a greedy brand eat a word
of the city; the general form is that every shape added is a shape a model can
misuse, so the set is kept small by policy. Induction waits for thirty lines
because below that the sample *is* the population and a fifth of it is three or
four lines, and the coverage gate is not 1.0 because a bank's long tail contains
genuine one-off lines — a grammar that honestly covers most of a statement is
worth more than one claiming all of it by being vague. Borrowing another bank's
grammar matters most for exactly the population the minimum creates, and a
borrowed match is recorded as layer `grammar` because it is structurally the same
claim.

Not merchant coverage, and not a business on the fallback. Plaid enriches 500M
transactions a day into a knowledge base built over years; the goal is *this
person's* few hundred merchants plus a commons for the tail. Enhanced merchant
data is becoming a regulatory floor — consume it where it exists, parse where it
does not.

## Open

- No quality gate measures whether a template **slotted correctly**, only whether
  it **matched**. A grammar can cover 90% of lines while putting cities in
  `{brand}` and pass every check. Only a person reading the grammar catches it,
  which is why using a grammar unattended is allowed and publishing one to the
  commons waits for a person.
- The vault holds at least one grammar whose template labelled a slot `brand`
  where an institution's name landed, with the party's name in slots the
  vocabulary treats as impersonal. No guard over slot *names* can see a party in
  a slot that does not name one. Closing it means re-inducing that grammar, or
  narrowing what counts as corroboration.
- The ACH corroboration clause is recovered from the corpus rather than read from
  a published boundary. The durable rule the measurement argues for is stricter,
  and this build does not implement it. Narrowing is one predicate,
  `corroborates_a_business`, plus a re-measurement.
- Both corroboration clauses are US-scope. On a rail proving neither — UPI, SEPA —
  every brand-slot hint is withheld, and no third signal exists in the code
  (I3, I5).
- Where a grammar's template names no brand at all, the key falls back to the
  whole normalized line, which crosses without passing through the corroboration
  gate or the substring fallback.
- A peer payment written in a language the marker list does not speak still
  crosses where no grammar exists (MER-19).
- The enrichment prompt does not say a brand string may be hard-truncated, so a
  clipped NACHA Company Name reads to a model as an odd brand name rather than a
  cut-off one (MER-32 in [merchantcore-package.md](merchantcore-package.md)).
- Widening the rail inference across institutions — so one brand paid on cards at
  two banks is one stream — is an open decision.
- Contribution of profiles to a commons waits until the lossless check has been
  measured on real statements.
- A merchant key publishing only once corroborated by independent vaults is
  unbuilt; the export filters on the key's shareability alone.
- `INDUCIBLE_KINDS` governs enrichment as well as induction and is narrower in
  name than in function.
- The Party primitive is unbuilt: there is no party event type and no `party`
  ruling scope. Its two day-one requirements stand — the same person across
  conduits, and meaning that generalizes, so *"John is my landlord"* makes every
  payment rent. This is the one place the field has no answer either: Plaid types
  the platform and has no `person` entity, Ntropy and Teller have `person` but no
  multi-party model, and nobody publishes accuracy on it, because a shared
  knowledge base cannot hold a private individual and every vendor is building
  one.
- Deliberately out of scope: merchant-as-Party unification; attributes of a party
  beyond a name; any attempt to identify a *person* from a name — the product
  learns that a party exists and what you say they are, and asks nobody else.
