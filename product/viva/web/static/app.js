/* OrionViva — the surface (Slice 6.9). Plain JavaScript, no build step.
 *
 * WHY NO BUILD. The previous surface was React compiled by Vite into this same
 * file. A compiled bundle can serve last hour's product with no error and no
 * way to tell by looking; verifying it meant grepping the output for feature
 * strings. That is the stale-artifact failure this project spent a week finding
 * everywhere else, sitting inside a repo whose discipline is that the artifact
 * must not lie. So: what you read here is what runs.
 *
 * THE ORGANISING IDEA. One card per instrument KIND — depository, liability,
 * investment, asserted — because the kind decides which figures exist and which
 * questions make sense. Every card carries the same three things:
 *
 *   1. the figure, with ITS OWN as-of date (never dressed as "current")
 *   2. its grade — `corroborated` means a document attests it AND the
 *      arithmetic checks; anything less says what is missing
 *   3. what it does NOT include — a card that silently omits is a lie of
 *      omission, which is the failure this product exists to refuse
 *
 * Money is FORMATTED here, never computed (T2). The ledger decided the figure.
 * See docs/the-surface-cards.md.
 */
'use strict'

// --- the server contract, in one place ---------------------------------------
// Kept whole and visible so a missing endpoint is obvious, and so the surface
// contract test can see that every endpoint the server exposes is called.
const json = {'Content-Type': 'application/json'}
const get = async (url) => {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${url} → ${r.status}`)
  return r.json()
}
const post = async (url, body, headers) => {
  const r = await fetch(url, {method: 'POST', body, headers: headers || json})
  if (!r.ok) throw new Error(`${url} → ${r.status}`)
  return r.json()
}

const api = {
  overview:     ()            => get('/api/overview'),
  greeting:     ()            => get('/api/greeting'),
  questions:    (limit = 10)  => get(`/api/questions?limit=${limit}`),
  decline:      (id, reason)  => post('/api/decline', JSON.stringify({id, reason})),
  netWorth:     (asOf = '')   => get(`/api/net-worth?as_of=${asOf}`),
  account:      (id)          => get(`/api/account?id=${encodeURIComponent(id)}`),
  review:       ()            => get('/api/review'),
  transfers:    ()            => get('/api/transfers'),
  paystubs:     ()            => get('/api/paystubs'),
  merchants:    ()            => get('/api/merchants'),
  categorize:   ()            => get('/api/categorize'),
  merchantTxns: (m)           => get(`/api/merchant-transactions?merchant=${encodeURIComponent(m)}`),

  confirmCorrection: (d)      => post('/api/confirm', JSON.stringify(d)),
  confirmIdentity:   (d)      => post('/api/confirm-identity', JSON.stringify(d)),
  confirmTransfer:   (a, b)   => post('/api/confirm-transfer', JSON.stringify({a, b})),
  rejectTransfer:    (a, b)   => post('/api/reject-transfer', JSON.stringify({a, b: b || ''})),
  assignCategory:    (k, c)   => post('/api/assign-category', JSON.stringify({key: k, category: c})),
  assignMerchant:    (m, c)   => post('/api/assign-merchant', JSON.stringify({merchant: m, category: c})),
  // The COMPLETE tag set for a subject; removing one means sending the set
  // without it. scope 'merchant' settles every movement from that counterparty.
  tag:        (subject, tags, scope) =>
                post('/api/tag', JSON.stringify({subject, tags, scope: scope || 'movement'})),
  // Takes a question option's `args` wholesale, so the surface never re-decides
  // the scope the queue already chose.
  ruleMajor:  (args)          => post('/api/rule-major', JSON.stringify(args)),
  listen:     (body)          => post('/api/listen', JSON.stringify(body)),
  applyRuling:(proposal)      => post('/api/apply-ruling', JSON.stringify({proposal})),
  upload:     (file)          => post('/api/upload', file, {'X-Filename': file.name}),
}

// --- formatting ---------------------------------------------------------------
function money(amount, currency) {
  if (amount === null || amount === undefined || amount === '') return ''
  const n = Number(amount)
  if (Number.isNaN(n)) return `${currency || ''} ${amount}`.trim()
  return `${currency ? currency + ' ' : ''}${n.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2})}`
}
/* The payload's shapes are not uniform — `ruled_accounts` is a list,
 * `undecomposed` is a map keyed by account, `holders` may be a string or a
 * list. Guessing produced `(ov.undecomposed || []).map is not a function`,
 * which took the whole page down.
 *
 * So: one helper that accepts any of them, rather than each renderer carrying
 * its own assumption about a shape it cannot see. */
const asRows = (v) => Array.isArray(v) ? v
  : (v && typeof v === 'object') ? Object.entries(v).map(([k, val]) =>
      (val && typeof val === 'object') ? {key: k, ...val} : {key: k, value: val})
  : v ? [v] : []

const esc = (s) => String(s == null ? '' : s).replace(/[&<>"']/g,
  c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]))

/* A figure is never shown without saying how old it is. Three of four accounts
 * on a real vault were measured months before the point they contributed to, so
 * "as of" is not a footnote here — it is part of the number. */
function asOfLabel(lineDate, pointDate) {
  if (!lineDate) return ''
  const stale = pointDate && lineDate !== pointDate
  return `as of ${esc(lineDate)}${stale ? ' · measured earlier' : ''}`
}

/* `corroborated` is the only grade that means PROVABLE: we hold the attesting
 * document and the arithmetic checks. Everything else is shown as what it is. */
const gradeNote = (g) => g === 'corroborated'
  ? '<span class="ok">a document attests this and the arithmetic checks</span>'
  : `<span class="why">${esc(g || 'ungraded')} — not yet provable</span>`

// --- the cards ----------------------------------------------------------------

const KINDS = [
  ['depository', 'What you hold', 'Cash in banks.'],
  ['liability', 'What you owe', 'Shown as the figure on your bill.'],
  ['investment', 'What you have invested', 'Cash held at the broker.'],
  ['holdings', 'Holdings', 'Valued at the last measurement on or before this date — a price is a measurement, never "current".'],
  ['asserted', 'What you told me you own', 'Recorded at COST — what you paid, never what it is worth now.'],
]

function netWorthCard(nw) {
  if (!nw || (!nw.lines.length && !nw.missing.length)) {
    return `<section class="card"><h3>What you're worth</h3>
      <div class="muted">Nothing to value yet — no dated measurement in this vault.
      That is the honest answer, not zero.</div></section>`
  }
  const rows = Object.entries(nw.by_currency).map(([cur, r]) => `
    <div class="row">
      <div class="grow">
        <div class="big">${esc(money(r.net, cur))}</div>
        <div class="quiet">${esc(money(r.assets, cur))} owned ·
          ${esc(money(r.liabilities, cur))} owed</div>
        <div class="quiet">${esc(money(r.provable, cur))} of it provable</div>
      </div>
    </div>`).join('')
  const stale = nw.oldest_input && nw.oldest_input !== nw.as_of
    ? `<div class="quiet">Only as current as its oldest input: ${esc(nw.oldest_input)}.</div>` : ''
  const incomplete = nw.complete ? '' :
    `<div class="why">Incomplete — your true net worth is <strong>lower</strong> than this.</div>`
  // A total that silently omits an obligation is the lie of omission this card
  // exists to refuse, so both lists are rendered, always.
  const missing = (nw.missing || []).map(m => `
    <div class="why"><strong>${esc(m.account)}</strong> is not counted —
      ${esc(m.why)}. ${esc(m.would_fix)} would settle it.</div>`).join('')
  const skipped = (nw.skipped || []).map(s => `
    <div class="quiet">${esc(s.account)} contributes nothing: ${esc(s.why)}</div>`).join('')
  return `<section class="card">
    <h3>What you're worth <span class="quiet">as of ${esc(nw.as_of)}</span></h3>
    ${incomplete}${rows}${stale}${missing}
    ${skipped ? `<details><summary>Accounts this total does not include</summary>${skipped}</details>` : ''}
  </section>`
}

/* ONE question at a time (Slice 6.10, D3) — Winston's rule made structural:
 * the queue ranks by consequence, the card shows rank #1 and says honestly how
 * many wait behind it. "Show me another" browses without recording anything;
 * "Not now" and "I don't know" are ANSWERS — recorded as decline events, so
 * the question stays quiet until new evidence changes its stake. */
function questionsCard(q) {
  const items = (q && q.questions) || []
  const ack = state.ack ? `<div class="quiet">${esc(state.ack)}</div>` : ''
  if (!items.length) {
    const settled = (state.greeting && state.greeting.all_settled)
      || 'Nothing right now. Everything I can settle, I have.'
    return `<section class="card"><h3>What Viva needs</h3>
      ${ack}<div class="muted">${esc(settled)}</div></section>`
  }
  const i = Math.min(state.qIndex || 0, items.length - 1)
  const item = items[i]
  const waiting = q.total - 1
  const one = `
    <div class="q">
      <div class="text">${esc(item.text)}</div>
      <div class="why">${esc(item.why || '')}</div>
      <div class="row">
        ${(item.options || []).map((o, j) =>
          `<button class="${j ? 'ghost' : ''}" data-answer="${i}" data-opt="${j}">${esc(o.label)}</button>`
        ).join('')}
        ${item.refs && item.refs.merchant
          ? `<button class="link" data-open="${esc(item.refs.merchant)}">see the transactions</button>` : ''}
      </div>
      ${item.free_text ? `
      <div class="row">
        <input type="text" id="said" class="grow"
               placeholder="${esc(item.free_text)}…">
      </div>
      <div id="proposal"></div>` : ''}
      <div class="row">
        <button class="link" data-decline="not_now">Not now</button>
        <button class="link" data-decline="dont_know">I don't know</button>
        ${items.length > 1
          ? `<button class="link" id="next-q">Show me another</button>` : ''}
      </div>
    </div>`
  return `<section class="card"><h3>What Viva needs
    <span class="quiet">${waiting > 0
      ? `${waiting} more waiting — most consequential first`
      : 'the last one'}</span></h3>
    ${ack}${one}</section>`
}

/* One card per kind. The lines come from net worth, which already carries every
 * honesty property a card needs — amount, its own as-of date, grade, origin and
 * the document behind it — so the cards are a GROUPING rather than a second
 * source of truth. Two systems describing one fact is the bug this project met
 * three times this month; the same lesson, applied to the surface. */
function kindCard(kind, title, blurb, lines, nw) {
  const mine = lines.filter(l => (l.kind || '').startsWith(kind))
  if (!mine.length) return ''
  const rows = mine.map(l => {
    // A liability is stored and displayed as money OWED — the figure on the
    // bill — while net worth carries it negative. The card speaks the person's
    // language; the arithmetic stays the ledger's.
    const owed = kind === 'liability'
    const shown = owed ? Math.abs(Number(l.amount)) : l.amount
    const credit = owed && Number(l.amount) > 0
    return `<div class="row account" data-account="${esc(l.account)}">
      <div class="grow">
        <div><strong>${esc(l.account)}</strong></div>
        <div class="quiet">${asOfLabel(l.as_of, nw.as_of)}</div>
        <div>${gradeNote(l.grade)}</div>
        ${l.origin === 'asserted'
          ? '<div class="quiet">your word — recorded at cost, not current value</div>' : ''}
        ${credit ? '<div class="why">This card owes YOU — a credit balance.</div>' : ''}
      </div>
      <div class="amt">${esc(money(shown, l.currency))}${owed && !credit ? ' owed' : ''}</div>
    </div>`
  }).join('')
  return `<section class="card"><h3>${esc(title)}</h3>
    <div class="quiet">${esc(blurb)}</div>${rows}</section>`
}


/* Where the money went. `spending_by_category` PARTITIONS — the parts sum to
 * the whole — so it is shown as a breakdown. `provisional_spending` is money
 * counted whose nature rests only on a hint, and `excluded_from_spending` is
 * money deliberately not counted (transfers between your own accounts). Both
 * are shown, because a spending figure that hides its own uncertainty is the
 * bug that started Slice 6.5. */
function spendingCard(ov) {
  if (!ov) return ''
  const cats = Object.entries(ov.spending_by_category || {})
    .sort((a, b) => Number(b[1]) - Number(a[1]))
  const subs = Object.entries(ov.spending_by_subcategory || {})
    .sort((a, b) => Number(b[1]) - Number(a[1])).slice(0, 12)
  if (!cats.length) return ''
  const rows = cats.map(([c, v]) =>
    `<div class="row"><div class="grow">${esc(c)}</div>
     <div class="amt">${esc(money(v, ov.currency))}</div></div>`).join('')
  const notes = []
  if (Number(ov.provisional_spending || 0))
    notes.push(`<div class="why">${esc(money(ov.provisional_spending, ov.currency))}
      of this is <strong>provisional</strong> — counted, but its nature rests on a
      hint rather than something you or a document confirmed.</div>`)
  if (Number(ov.excluded_from_spending || 0))
    notes.push(`<div class="quiet">${esc(money(ov.excluded_from_spending, ov.currency))}
      excluded — money that moved between your own accounts never left your life.</div>`)
  return `<section class="card"><h3>Where it went</h3>${rows}${notes.join('')}
    ${subs.length ? `<details><summary>Finer detail</summary>${subs.map(([c, v]) =>
      `<div class="row"><div class="grow">${esc(c)}</div>
       <div class="amt">${esc(money(v, ov.currency))}</div></div>`).join('')}</details>` : ''}
  </section>`
}

/* What came in. Income is recognised once, from the pay stub, and decomposed —
 * so the breakdown names the withheld parts rather than showing only the net. */
function incomeCard(ov) {
  if (!ov || !Number(ov.income || 0)) return ''
  const rows = asRows(ov.income_breakdown).map(r =>
    `<div class="row"><div class="grow">${esc(r.key || r.label || '')}</div>
     <div class="amt">${esc(money(r.value !== undefined ? r.value : r.amount, ov.currency))}</div>
     </div>`).join('')
  return `<section class="card"><h3>What came in</h3>
    <div class="big">${esc(money(ov.income, ov.currency))}</div>${rows}</section>`
}

/* Holdings, each with ITS OWN measurement date (M1: a price is a measurement,
 * never "current"), and the accounts a ruling of yours brought into being —
 * with `undecomposed` naming the money whose components are known but whose
 * proportions are not. Neither counted nor dropped: said. */
function holdingsCard(ov) {
  if (!ov) return ''
  const pos = asRows(ov.positions)
  const ruled = asRows(ov.ruled_accounts)
  if (!pos.length && !ruled.length) return ''
  const rows = pos.map(h => `<div class="row"><div class="grow">
      <strong>${esc(h.instrument || h.name || '')}</strong>
      <div class="quiet">as of ${esc(h.as_of || '')} · ${esc(h.valuation_class || 'measured')}</div>
    </div><div class="amt">${esc(money(h.market_value, h.currency))}</div></div>`).join('')
  const mine = ruled.map(r => `<div class="row"><div class="grow">
      <strong>${esc(r.account)}</strong>
      <div class="quiet">${esc(r.origin || 'asserted')} · recorded at cost
      ${r.reliable_balance === false ? ' · balance not reliable' : ''}</div>
    </div><div class="amt">${esc(money(r.paid, r.currency))}</div></div>`).join('')
  const und = asRows(ov.undecomposed).map(u => `<div class="why">
      ${esc(u.account || u.key || u.description || '')} — components known, proportions not.
      Neither counted nor dropped until the paperwork says how it splits.</div>`).join('')
  return `<section class="card"><h3>Holdings and things you own</h3>
    ${rows}${mine}${und}</section>`
}

/* How complete is this picture? `coverage` is the product telling the truth
 * about its own gaps, which is worth more than a confident total. */
function coverageCard(ov) {
  if (!ov || !ov.coverage) return ''
  const c = ov.coverage
  return `<section class="card"><h3>What I have to go on</h3>
    <div class="quiet">${esc(typeof c === 'string' ? c : JSON.stringify(c))}</div>
    ${ov.holders ? `<div class="quiet">held by ${esc(asRows(ov.holders).join(', '))}</div>` : ''}
    ${ov.institution ? `<div class="quiet">${esc(ov.institution)}</div>` : ''}
  </section>`
}

function addDocumentsCard() {
  return `<section class="card"><h3>Add documents</h3>
    <input type="file" id="upload" multiple accept="application/pdf">
    <div class="quiet" id="upload-status"></div></section>`
}

// --- the page -----------------------------------------------------------------

const root = document.getElementById('root')
let state = {nw: null, questions: null, overview: null, greeting: null,
             qIndex: 0, ack: '', proposal: null}

/* A card that throws must not take the page down with it.
 *
 * It did: one wrong assumption about the shape of `undecomposed` replaced the
 * entire surface with "I can't reach the ledger" — which was also a LIE, since
 * the ledger was reached perfectly and every other card had its data in hand.
 * A whole page lost, and a misleading reason given for losing it.
 *
 * The right behaviour is the one this project applies everywhere else: fail
 * narrowly, say what failed, and keep showing everything that is fine. */
function safely(name, fn) {
  try { return fn() } catch (e) {
    return `<section class="card"><h3>${esc(name)}</h3>
      <div class="why">This card could not be drawn: ${esc(e.message)}.
      The rest of the page is unaffected, and your ledger is fine — this is a
      rendering fault, not a data one.</div></section>`
  }
}

function render() {
  const {nw, questions, overview, greeting} = state
  const lines = (nw && nw.lines) || []
  root.innerHTML = [
    // Viva's opening line — a moment from the persona pack, never hardcoded.
    greeting && greeting.text
      ? `<div class="quiet greeting">${esc(greeting.text)}</div>` : '',
    safely("What you're worth", () => netWorthCard(nw)),
    safely('What Viva needs', () => questionsCard(questions)),
    ...KINDS.map(([k, t, b]) => safely(t, () => kindCard(k, t, b, lines, nw || {}))),
    safely('Holdings and things you own', () => holdingsCard(overview)),
    safely('Where it went', () => spendingCard(overview)),
    safely('What came in', () => incomeCard(overview)),
    safely('What I have to go on', () => coverageCard(overview)),
    addDocumentsCard(),
  ].join('')
  wire()
}

function wire() {
  root.querySelectorAll('[data-answer]').forEach(el => {
    el.addEventListener('click', async () => {
      const q = state.questions.questions[Number(el.dataset.answer)]
      const opt = q.options[Number(el.dataset.opt)]
      el.disabled = true
      try {
        if (opt.action === 'rule_major') {
          await api.ruleMajor({descriptor: (q.refs && (q.refs.descriptor || q.refs.example)) || '',
                               ...opt.args})
        } else if (opt.action === 'confirm_transfer') {
          await api.confirmTransfer(opt.args.movement_a, opt.args.movement_b)
        } else if (opt.action === 'reject_transfer') {
          await api.rejectTransfer(opt.args.movement_a)
        } else if (opt.action === 'assign_merchant') {
          return openMerchant(opt.args.merchant)
        } else if (opt.action === 'confirm_identity') {
          // args carry {doc_id, decision: 'same' | 'new'} wholesale from the
          // queue — the same pass-through rule ruleMajor follows.
          await api.confirmIdentity(opt.args)
        } else if (opt.action === 'upload') {
          // No flow of its own: the Add-documents card IS the answer.
          el.disabled = false
          const target = document.getElementById('upload')
          if (target) target.scrollIntoView({behavior: 'smooth'})
          return
        } else if (opt.action === 'dismiss') {
          // "Not right now" is an ANSWER (6.10): recorded as a decline, quiet
          // until new evidence changes the question's stake.
          const r = await api.decline(q.id, 'not_now')
          state.ack = r.message || ''
          state.qIndex = 0
        } else if (opt.action === 'review') {
          // Named here so the action contract test can see it is KNOWN, and
          // answered honestly: no flow exists behind it yet. The alternative
          // — a button that does nothing, silently — is how the Imprint
          // identity question sat unanswerable (found 2026-07-27).
          el.disabled = false
          alert(`"${opt.label}" has no flow built behind it yet — nothing was recorded.`)
          return
        } else {
          // An action this surface has never heard of must say so, not no-op.
          el.disabled = false
          alert(`This button ("${opt.label}") is wired to nothing this surface knows — nothing was recorded.`)
          return
        }
        await load()
      } catch (e) { el.disabled = false; alert(e.message) }
    })
  })
  root.querySelectorAll('[data-open]').forEach(el => {
    el.addEventListener('click', () => openMerchant(el.dataset.open))
  })
  // Declining IS answering (6.10): the server snapshots the live stake and
  // replies in Viva's voice; the question returns only on new evidence.
  root.querySelectorAll('[data-decline]').forEach(el => {
    el.addEventListener('click', async () => {
      const items = state.questions.questions
      const item = items[Math.min(state.qIndex || 0, items.length - 1)]
      el.disabled = true
      try {
        const r = await api.decline(item.id, el.dataset.decline)
        state.ack = r.message || ''
        state.qIndex = 0
        await load()
      } catch (e) { el.disabled = false; alert(e.message) }
    })
  })
  const nextQ = document.getElementById('next-q')
  if (nextQ) nextQ.addEventListener('click', () => {
    // Browsing, not answering — nothing is recorded, the ranking stands.
    state.qIndex = ((state.qIndex || 0) + 1) % state.questions.questions.length
    state.ack = ''
    render()
  })
  // "Tell me in your own words" (9a, finally on the surface): sentence →
  // proposal shown back in plain language → explicit yes → deterministic
  // writers. Nothing is written until the person confirms (X3).
  const said = document.getElementById('said')
  if (said) said.addEventListener('keydown', async (e) => {
    if (e.key !== 'Enter' || !e.target.value.trim()) return
    const items = state.questions.questions
    const item = items[Math.min(state.qIndex || 0, items.length - 1)]
    const refs = item.refs || {}
    const box = document.getElementById('proposal')
    box.innerHTML = `<div class="quiet">reading…</div>`
    try {
      const r = await api.listen({
        said: e.target.value.trim(),
        descriptor: refs.descriptor || refs.example || '',
        movement_key: refs.movement || '',
        category: refs.category || '', subcategory: refs.subcategory || '',
        amount: item.amount || '', currency: item.currency || ''})
      if (!r.understood) {
        box.innerHTML = `<div class="why">${esc(r.message || "I couldn't read that one — the buttons still work.")}</div>`
        return
      }
      state.proposal = r.proposal
      box.innerHTML = `
        <div class="why">${esc(r.proposal.summary || 'Here is what I understood.')}</div>
        <div class="row">
          <button id="apply-proposal">Yes — do that</button>
          <button class="ghost" id="cancel-proposal">No, hold on</button>
        </div>`
      document.getElementById('apply-proposal').addEventListener('click', async () => {
        await api.applyRuling(state.proposal)
        state.proposal = null
        state.qIndex = 0
        await load()
      })
      document.getElementById('cancel-proposal').addEventListener('click', () => {
        state.proposal = null
        box.innerHTML = ''
      })
    } catch (err) { box.innerHTML = `<div class="why">${esc(err.message)}</div>` }
  })
  root.querySelectorAll('[data-account]').forEach(el => {
    el.addEventListener('click', () => openAccount(el.dataset.account))
  })
  const up = document.getElementById('upload')
  if (up) up.addEventListener('change', async () => {
    const status = document.getElementById('upload-status')
    for (const f of up.files) {
      status.textContent = `reading ${f.name}…`
      try { const r = await api.upload(f); status.textContent = r.message || 'done' }
      catch (e) { status.textContent = e.message }
    }
    await load()
  })
}

async function openAccount(id) {
  const d = await api.account(id)
  const rows = (d.transactions || d.lines || []).slice(0, 300).map(t => `
    <tr><td>${esc(t.date)}</td><td>${esc(t.description)}</td>
        <td class="num">${esc(money(t.amount, t.currency || d.currency))}</td></tr>`).join('')
  root.innerHTML = `<section class="card">
    <a class="back" href="#" id="back">← back</a>
    <h3>${esc(id)}</h3>
    <table><thead><tr><th>Date</th><th>Description</th><th class="num">Amount</th></tr></thead>
    <tbody>${rows}</tbody></table></section>`
  document.getElementById('back').addEventListener('click', (e) => { e.preventDefault(); render() })
}

/* The drill-through is where ANSWERING happens: a card is for reading, and
 * answering is a deliberate act. Category and tags are two separate controls
 * because they are different kinds of statement — a category PARTITIONS (one
 * per movement, the parts sum to the whole) and a tag OVERLAYS (many, and the
 * totals deliberately do not sum). Merging the controls would rebuild the
 * confusion the split exists to remove. */
async function openMerchant(merchant) {
  const d = await api.merchantTxns(merchant)
  /* Direction is part of the number. Amounts arrive SIGNED with a kind-aware
   * `direction`; showing magnitudes alone made every EFT to the broker read
   * positive and dressed a gross two-way total as one figure. The magnitude
   * here is display (like the liability card's "owed"); the ledger decided
   * out/in and the three summary figures. */
  const rows = (d.items || []).map(t => `
    <tr><td>${esc(t.date)}</td><td>${esc(t.description)}</td>
        <td>${esc(t.category || '')}</td>
        <td class="quiet">${esc((t.tags || []).join(', '))}</td>
        <td class="num">${t.direction === 'in' ? '+' : '−'}&nbsp;${esc(money(Math.abs(Number(t.amount)), t.currency))}</td></tr>`).join('')
  const known = (d.known_tags || []).filter(t => !(d.merchant_tags || []).includes(t))
  const bothWays = Number(d.money_out) > 0 && Number(d.money_in) > 0
  const flow = bothWays
    ? `${esc(money(d.money_out, d.currency))} out · ${esc(money(d.money_in, d.currency))} in
       · net ${esc(money(Math.abs(Number(d.net)), d.currency))} ${Number(d.net) >= 0 ? 'out' : 'in'}`
    : Number(d.money_in) > 0
      ? `${esc(money(d.money_in, d.currency))} in`
      : `${esc(money(d.money_out, d.currency))} out`
  root.innerHTML = `<section class="card">
    <a class="back" href="#" id="back">← back</a>
    <h3>${esc(d.merchant)}</h3>
    <div class="quiet">${d.count} transaction(s) · ${flow}</div>

    <div class="row" style="margin-top:12px">
      <select id="cat">${(d.categories || []).map(c =>
        `<option value="${esc(c)}">${esc(c)}</option>`).join('')}</select>
      <button id="assign">Categorize everywhere</button>
    </div>

    <div style="margin-top:12px">
      <div class="quiet">Tags — as many as you like. They never change what kind
        of spending this is.</div>
      <div class="row">
        ${(d.merchant_tags || []).map(t =>
          `<button class="ghost" data-untag="${esc(t)}">${esc(t)} ×</button>`).join('')}
        <input type="text" id="newtag" class="grow" placeholder="add a tag…">
      </div>
      ${known.length ? `<div class="row"><span class="quiet">already used:</span>
        ${known.slice(0, 12).map(t => `<button class="link" data-addtag="${esc(t)}">${esc(t)}</button>`).join('')}
      </div>` : ''}
    </div>

    <table><thead><tr><th>Date</th><th>Description</th><th>Category</th><th>Tags</th>
      <th class="num">Amount</th></tr></thead><tbody>${rows}</tbody></table>
  </section>`

  const current = () => Array.from(root.querySelectorAll('[data-untag]')).map(b => b.dataset.untag)
  const save = async (tags) => { await api.tag(d.merchant, tags, 'merchant'); openMerchant(merchant) }
  document.getElementById('back').addEventListener('click', (e) => { e.preventDefault(); render() })
  document.getElementById('assign').addEventListener('click', async () => {
    await api.assignMerchant(d.merchant, document.getElementById('cat').value)
    await load()
  })
  root.querySelectorAll('[data-untag]').forEach(b => b.addEventListener('click',
    () => save(current().filter(t => t !== b.dataset.untag))))
  root.querySelectorAll('[data-addtag]').forEach(b => b.addEventListener('click',
    () => save(current().concat([b.dataset.addtag]))))
  document.getElementById('newtag').addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return
    const v = e.target.value.trim().toLowerCase()
    if (v && !current().includes(v)) save(current().concat([v]))
  })
}

async function load() {
  try {
    const [nw, questions, overview, greeting] = await Promise.all([
      api.netWorth().catch(() => null),
      api.questions(10).catch(() => ({questions: [], total: 0})),
      api.overview().catch(() => null),
      api.greeting().catch(() => null),
    ])
    state = {...state, nw, questions, overview, greeting,
             qIndex: Math.min(state.qIndex, Math.max(0, (questions.questions || []).length - 1))}
    render()
    state.ack = ''                       // an ack shows once, then retires
  } catch (e) {
    // Only reached when a FETCH failed. A rendering fault is caught per card
    // above, because blaming the ledger for a display bug sends you looking in
    // the wrong place — which is exactly what happened the first time.
    root.innerHTML = `<div class="card"><h3>I can't reach the ledger</h3>
      <div class="muted">${esc(e.message)}</div>
      <div class="quiet">This is a connection problem, not your data.</div></div>`
  }
}

load()
