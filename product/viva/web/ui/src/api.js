// Every call the surface makes. Kept in one file so the page↔server contract is
// readable in one screen — and so a missing endpoint is obvious.

const json = {'Content-Type': 'application/json'}

async function get(url) {
  const r = await fetch(url)
  if (!r.ok) throw new Error(`${url} → ${r.status}`)
  return r.json()
}
async function post(url, body, headers) {
  const r = await fetch(url, {method: 'POST', body, headers: headers || json})
  if (!r.ok) throw new Error(`${url} → ${r.status}`)
  return r.json()
}

export const api = {
  overview:   ()             => get('/api/overview'),
  questions:  (limit = 10)   => get(`/api/questions?limit=${limit}`),
  account:    (id)           => get(`/api/account?id=${encodeURIComponent(id)}`),
  review:     ()             => get('/api/review'),
  netWorth:   (asOf = '')    => get(`/api/net-worth?as_of=${asOf}`),
  transfers:  ()             => get('/api/transfers'),
  paystubs:   ()             => get('/api/paystubs'),
  merchants:  ()             => get('/api/merchants'),
  categorize: ()             => get('/api/categorize'),
  merchantTxns: (m)          => get(`/api/merchant-transactions?merchant=${encodeURIComponent(m)}`),

  confirmCorrection: (d)     => post('/api/confirm', JSON.stringify(d)),
  confirmIdentity:   (d)     => post('/api/confirm-identity', JSON.stringify(d)),
  confirmTransfer:   (a, b)  => post('/api/confirm-transfer', JSON.stringify({a, b})),
  rejectTransfer:    (a, b)  => post('/api/reject-transfer', JSON.stringify({a, b: b || ''})),
  assignCategory:    (k, c)  => post('/api/assign-category', JSON.stringify({key: k, category: c})),
  // The COMPLETE tag set for a subject — removing a tag is sending the set
  // without it. scope 'merchant' settles every movement from that counterparty.
  tag:        (subject, tags, scope) => post('/api/tag', JSON.stringify({subject, tags, scope: scope || 'movement'})),
  assignMerchant:    (m, c)  => post('/api/assign-merchant', JSON.stringify({merchant: m, category: c})),
  // Slice 9a. ruleMajor is the button path (deterministic, no model);
  // listen reads a sentence and returns a PROPOSAL, writing nothing;
  // applyRuling is the explicit yes that makes it real.
  // Takes a question option's `args` wholesale — {major, merchant?,
  // movement_key?, group?} — so the surface never has to know which scope a
  // question is asking at. The queue already decided that; re-deciding it here
  // is how movement-scoped answers lost their key.
  ruleMajor:  (args)        => post('/api/rule-major', JSON.stringify(args)),
  listen:     (body)        => post('/api/listen', JSON.stringify(body)),
  applyRuling:(proposal)    => post('/api/apply-ruling', JSON.stringify({proposal})),
  upload:            (file)  => post('/api/upload', file, {'X-Filename': file.name}),
}

// Money is formatted, never computed, in the surface (T2): the ledger already
// decided the figure; we only decide how it reads.
export function money(amount, currency) {
  if (amount === null || amount === undefined || amount === '') return ''
  const n = Number(amount)
  if (Number.isNaN(n)) return `${currency || ''} ${amount}`.trim()
  return `${currency ? currency + ' ' : ''}${n.toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2})}`
}
