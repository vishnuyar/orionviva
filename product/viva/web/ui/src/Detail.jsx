import {useEffect, useState} from 'react'
import {api, money} from './api'

/* The focused view for a question that needs context (Slice 6.7 D1: hybrid).
 * The queue stays scannable; this is where a decision gets room. */

export function AccountView({id, onBack}) {
  const [d, setD] = useState(null)
  useEffect(() => { api.account(id).then(setD) }, [id])
  if (!d) return <div className="card muted">Loading…</div>
  if (d.error) return (
    <div className="card">
      <a className="back" onClick={onBack}>← back</a>
      <p className="muted">I don't hold an account called {id}.</p>
    </div>
  )
  return (
    <div className="card">
      <a className="back" onClick={onBack}>← back</a>
      <h3 style={{marginTop: 10}}>{d.name}</h3>
      <div className="src">{[d.institution, d.number].filter(Boolean).join(' ')}
        {d.holders?.length ? ' · ' + d.holders.join(', ') : ''}</div>
      <div className="quiet">{d.balance.explanation}</div>
      <table>
        <thead><tr><th>Date</th><th>Description</th><th className="amt">Amount</th></tr></thead>
        <tbody>
          {d.transactions.map((t, i) => (
            <tr key={i}>
              <td>{t.date}</td>
              <td>{t.description}<div className="src">{t.provenance?.doc_id?.slice(0, 10)}</div></td>
              <td className="amt">{money(t.amount, d.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* A held statement — the one question that always needs the document in view.
 * Reuses the existing correction flow: the person supplies the value, the same
 * deterministic gate decides whether it now reconciles. */
export function HeldDetail({docId, onBack, onDone}) {
  const [items, setItems] = useState(null)
  const [value, setValue] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.review().then(r => setItems(r.items)) }, [])
  if (!items) return <div className="card muted">Loading…</div>
  const it = items.find(x => x.doc_id === docId)
  if (!it) return (
    <div className="card">
      <a className="back" onClick={onBack}>← back</a>
      <p className="muted">That document isn't waiting any more.</p>
    </div>
  )
  const f = it.finding || {}
  const target = f.target_index != null ? f.target_index : null
  return (
    <div className="card">
      <a className="back" onClick={onBack}>← back</a>
      <h3 style={{marginTop: 10}}>{it.account_label} · {it.period}</h3>
      <div className="quiet">{f.message || 'This statement did not reconcile.'}</div>
      <div className="row" style={{marginTop: 10}}>
        <span className="tiny">opens {money(it.opening_amount, it.currency)} →
          closes {money(it.closing_amount, it.currency)}</span>
      </div>
      {f.status && f.status !== 'none' && (
        <div className="row" style={{marginTop: 10}}>
          <input type="text" placeholder={f.implied || 'the correct figure'}
                 value={value} onChange={e => setValue(e.target.value)} />
          <button disabled={busy || !value} onClick={async () => {
            setBusy(true)
            try {
              await api.confirmCorrection({
                doc_id: docId,
                field: f.kind === 'balance_misread' ? 'closing' : 'amount',
                value, target_index: target})
              await onDone()
            } finally { setBusy(false) }
          }}>That's the right figure</button>
        </div>
      )}
      <table>
        <thead><tr><th>Date</th><th>Description</th><th className="amt">Amount</th></tr></thead>
        <tbody>
          {(it.transactions || []).map((t, i) => (
            <tr key={i} style={i === target ? {background: '#fdfaf1'} : undefined}>
              <td>{t.date}</td><td>{t.description}</td>
              <td className="amt">{money(t.amount, it.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* A merchant's transactions — the context behind "what is this?" and "is this
 * spending?". Keyed on the NORMALIZED merchant, so what you see is exactly what
 * your answer will settle. A peer descriptor is answered per transaction (one
 * Zelle is a gift, the next a loan repayment); a commercial merchant once. */
export function MerchantDetail({q, onBack, onDone}) {
  const [d, setD] = useState(null)
  const [cat, setCat] = useState('')
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.merchantTxns(q.refs.merchant).then(setD) }, [q.refs.merchant])
  if (!d) return <div className="card muted">Loading…</div>
  const cats = q.refs.categories || d.categories || []
  const chosen = cat || cats[0] || ''
  const perTransaction = q.scope === 'one'
  return (
    <div className="card">
      <a className="back" onClick={onBack}>← back</a>
      <h3 style={{marginTop: 10}}>{q.refs.example || d.merchant}</h3>
      <div className="quiet">{q.text}</div>
      <div className="quiet">
        {d.count} transaction{d.count === 1 ? '' : 's'} · {money(d.total, d.currency)} in total
      </div>
      {/* The three hard-coded natures that stood here until 2026-07-26 —
          spending / transfer / settlement — were replaced by the four majors in
          Slice 9a, and "settlement" had always been mislabelled ("something I
          now own" when it meant debt repayment). The options now come from the
          QUESTION, which is where the intelligence lives: the queue already
          knows whether it is proposing a relationship or asking outright. */}
      {q.kind === 'nature' ? (
        <div className="row" style={{marginTop: 12}}>
          {(q.options || []).map(o => (
            <button key={o.label} className={o === q.options[0] ? '' : 'ghost'}
                    disabled={busy} onClick={async () => {
              setBusy(true)
              try {
                await api.ruleMajor({descriptor: q.refs.descriptor || d.merchant,
                                     ...o.args})
                await onDone()
              } finally { setBusy(false) }
            }}>{o.label}</button>
          ))}
        </div>
      ) : !perTransaction && (
        <div className="row" style={{marginTop: 12}}>
          <select value={chosen} onChange={e => setCat(e.target.value)}>
            {cats.map(c => <option key={c} value={c}>{c}</option>)}
          </select>
          <button disabled={busy || !chosen} onClick={async () => {
            setBusy(true)
            try { await api.assignMerchant(d.merchant, chosen); await onDone() }
            finally { setBusy(false) }
          }}>Categorize everywhere</button>
        </div>
      )}
      <table>
        <thead><tr><th>Date</th><th>Description</th>
          <th className="amt">Amount</th>{perTransaction && <th></th>}</tr></thead>
        <tbody>
          {d.items.map(t => (
            <tr key={t.key}>
              <td>{t.date}</td>
              <td>{t.description}
                <div className="src">
                  {t.category || 'uncategorized'}
                  {t.counts_as_spending ? '' : ` · not counted as spending (${t.nature})`}
                </div></td>
              <td className="amt">{money(t.amount, t.currency)}</td>
              {perTransaction && (
                <td className="amt">
                  <PerTransaction txn={t} cats={cats} onDone={onDone} />
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/* Peer payments vary one to the next, so each gets its own answer (the
 * local-categorization ruling). Wires /api/assign-category, built in Slice 5 and
 * reachable only by curl until now. */
function PerTransaction({txn, cats, onDone}) {
  const [c, setC] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <span className="row" style={{justifyContent: 'flex-end'}}>
      <select value={c || cats[0] || ''} onChange={e => setC(e.target.value)}>
        {cats.map(x => <option key={x} value={x}>{x}</option>)}
      </select>
      <button className="ghost" disabled={busy} onClick={async () => {
        setBusy(true)
        try { await api.assignCategory(txn.key, c || cats[0]); await onDone() }
        finally { setBusy(false) }
      }}>Set</button>
    </span>
  )
}

/* Two sides of a possible transfer, so "is this the same money?" is answerable
 * by looking rather than trusting. */
export function TransferDetail({q, onBack, onDone}) {
  const [d, setD] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.transfers().then(setD) }, [])
  const item = (d?.items || []).find(i => i.source.key === q.refs.movement)
  if (!d) return <div className="card muted">Loading…</div>
  if (!item) return (
    <div className="card"><a className="back" onClick={onBack}>← back</a>
      <p className="muted">That one is already settled.</p></div>
  )
  const line = (m) => (
    <div className="q"><div className="between">
      <span>{m.date} · {m.description}<div className="src">{m.account}</div></span>
      <span className="stake">{money(m.amount, '')}</span>
    </div></div>
  )
  return (
    <div className="card">
      <a className="back" onClick={onBack}>← back</a>
      <h3 style={{marginTop: 10}}>Is this the same money?</h3>
      <div className="quiet">Money moving between your own accounts isn't spending.</div>
      {line(item.source)}
      <div className="tiny" style={{margin: '8px 0'}}>could be the other side of:</div>
      {item.candidates.map(c => (
        <div key={c.key}>
          {line(c)}
          <button disabled={busy} onClick={async () => {
            setBusy(true)
            try { await api.confirmTransfer(item.source.key, c.key); await onDone() }
            finally { setBusy(false) }
          }}>Yes — same money</button>
        </div>
      ))}
      <div style={{marginTop: 12}}>
        <button className="ghost" disabled={busy} onClick={async () => {
          setBusy(true)
          try { await api.rejectTransfer(item.source.key); await onDone() }
          finally { setBusy(false) }
        }}>None of these — it's spending</button>
      </div>
    </div>
  )
}
