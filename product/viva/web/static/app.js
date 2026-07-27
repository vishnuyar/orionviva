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
  questions:    (limit = 10)  => get(`/api/questions?limit=${limit}`),
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

function questionsCard(q) {
  const items = (q && q.questions) || []
  if (!items.length) {
    return `<section class="card"><h3>What Viva needs</h3>
      <div class="muted">Nothing right now. Everything I can settle, I have.</div></section>`
  }
  // Ranked by CONSEQUENCE — answer the one that moves the most money first.
  const rows = items.map((item, i) => `
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
    </div>`).join('')
  return `<section class="card"><h3>What Viva needs
    <span class="quiet">${items.length} of ${q.total}, most consequential first</span></h3>
    ${rows}</section>`
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
  const rows = Object.entries(ov.income_breakdown || {}).map(([k, v]) =>
    `<div class="row"><div class="grow">${esc(k)}</div>
     <div class="amt">${esc(money(v, ov.currency))}</div></div>`).join('')
  return `<section class="card"><h3>What came in</h3>
    <div class="big">${esc(money(ov.income, ov.currency))}</div>${rows}</section>`
}

/* Holdings, each with ITS OWN measurement date (M1: a price is a measurement,
 * never "current"), and the accounts a ruling of yours brought into being —
 * with `undecomposed` naming the money whose components are known but whose
 * proportions are not. Neither counted nor dropped: said. */
function holdingsCard(ov) {
  if (!ov) return ''
  const pos = ov.positions || []
  const ruled = Object.values(ov.ruled_accounts || {})
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
  const und = (ov.undecomposed || []).map(u => `<div class="why">
      ${esc(u.description || u.account || '')} — components known, proportions not.
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
    ${ov.holders ? `<div class="quiet">held by ${esc([].concat(ov.holders).join(', '))}</div>` : ''}
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
let state = {nw: null, questions: null, overview: null}

function render() {
  const {nw, questions} = state
  const lines = (nw && nw.lines) || []
  root.innerHTML = [
    netWorthCard(nw),
    questionsCard(questions),
    ...KINDS.map(([k, t, b]) => kindCard(k, t, b, lines, nw || {})),
    holdingsCard(state.overview),
    spendingCard(state.overview),
    incomeCard(state.overview),
    coverageCard(state.overview),
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
        }
        await load()
      } catch (e) { el.disabled = false; alert(e.message) }
    })
  })
  root.querySelectorAll('[data-open]').forEach(el => {
    el.addEventListener('click', () => openMerchant(el.dataset.open))
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
  const rows = (d.items || []).map(t => `
    <tr><td>${esc(t.date)}</td><td>${esc(t.description)}</td>
        <td>${esc(t.category || '')}</td>
        <td class="quiet">${esc((t.tags || []).join(', '))}</td>
        <td class="num">${esc(money(t.amount, t.currency))}</td></tr>`).join('')
  const known = (d.known_tags || []).filter(t => !(d.merchant_tags || []).includes(t))
  root.innerHTML = `<section class="card">
    <a class="back" href="#" id="back">← back</a>
    <h3>${esc(d.merchant)}</h3>
    <div class="quiet">${d.count} transaction(s) · ${esc(money(d.total, d.currency))} in total</div>

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
    const [nw, questions, overview] = await Promise.all([
      api.netWorth().catch(() => null),
      api.questions(10).catch(() => ({questions: [], total: 0})),
      api.overview().catch(() => null),
    ])
    state = {nw, questions, overview}
    render()
  } catch (e) {
    root.innerHTML = `<div class="card"><h3>I can't reach the ledger</h3>
      <div class="muted">${esc(e.message)}</div></div>`
  }
}

load()
