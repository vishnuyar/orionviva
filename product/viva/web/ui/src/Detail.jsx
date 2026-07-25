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

/* A merchant's transactions — the context behind "is this spending?" and
 * "what is this?". Also where a peer descriptor is answered per transaction. */
export function MerchantDetail({q, onBack, onDone}) {
  const [d, setD] = useState(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { api.categorize().then(setD) }, [])
  const cats = q.refs.categories || d?.categories || []
  const [cat, setCat] = useState('')
  const rows = (d?.items || []).filter(
    i => (i.descriptor || '').toLowerCase().includes((q.refs.example || '').toLowerCase().slice(0, 12)))
  return (
    <div className="card">
      <a className="back" onClick={onBack}>← back</a>
      <h3 style={{marginTop: 10}}>{q.refs.example || q.refs.merchant}</h3>
      <div className="quiet">{q.text}</div>
      <div className="row" style={{marginTop: 10}}>
        <select value={cat || cats[0] || ''} onChange={e => setCat(e.target.value)}>
          {cats.map(c => <option key={c} value={c}>{c}</option>)}
        </select>
        <button disabled={busy} onClick={async () => {
          setBusy(true)
          try { await api.assignMerchant(q.refs.merchant, cat || cats[0]); await onDone() }
          finally { setBusy(false) }
        }}>Categorize everywhere</button>
      </div>
      {rows.length > 0 && (
        <table>
          <thead><tr><th>Date</th><th>Description</th><th className="amt">Amount</th></tr></thead>
          <tbody>
            {rows.slice(0, 40).map((t, i) => (
              <tr key={i}><td>{t.date}</td><td>{t.descriptor}</td>
                <td className="amt">{money(t.amount, t.currency)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
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
