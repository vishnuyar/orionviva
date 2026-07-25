import {useCallback, useEffect, useState} from 'react'
import {api, money} from './api'
import Questions from './Questions'
import {AccountView, HeldDetail, MerchantDetail, TransferDetail} from './Detail'

/* The spine, in the order a person actually wants it:
 *   the picture → what Viva needs → your money → where it went → add documents.
 * Dashboard-first and speak-only-when-spoken-to (Vishnu's experience-vision
 * calls): findings are quiet state on the page, never notifications. Progressive
 * disclosure throughout — a panel that has nothing to say does not appear. */

function Picture({d}) {
  const t = d.total
  const provisional = Number(d.provisional_spending || 0)
  const [open, setOpen] = useState(false)
  const excluded = d.excluded_from_spending || []
  const byReason = excluded.reduce((acc, m) => {
    const label = {linked: 'confirmed transfers', own_account: 'went to an account you hold',
                   ruling: 'you told me', category_hint: 'looks internal — unconfirmed'}[m.reason] || m.reason
    acc[label] = (acc[label] || 0) + Math.abs(Number(m.amount))
    return acc
  }, {})
  return (
    <div className="card total">
      {t.answered && t.amount != null ? (
        <>
          <div className="lbl">Total across your accounts</div>
          <div className="amt">{money(t.amount, t.currency)}</div>
        </>
      ) : t.answered ? (
        <>
          <div className="lbl">Across currencies (not converted)</div>
          <div className="amt" style={{fontSize: 22}}>
            {Object.entries(t.subtotals || {}).map(([c, v]) => `${c} ${v}`).join(' · ')}</div>
        </>
      ) : (
        <><div className="lbl">Total</div><div className="muted">{t.text}</div></>
      )}
      <div className="quiet">{d.coverage}</div>
      {d.spending?.text && <div className="quiet">{d.spending.text}</div>}
      {/* X2: the figure states its own uncertainty, quietly and without alarm. */}
      {provisional > 0 && (
        <div className="quiet">
          I've kept {money(d.provisional_spending, d.spending?.currency)} out of spending on a
          hint alone — <button className="link" onClick={() => setOpen(!open)}>
            {open ? 'hide' : "show me what I left out"}</button>
        </div>
      )}
      {open && (
        <table>
          <tbody>
            {Object.entries(byReason).sort((a, b) => b[1] - a[1]).map(([label, amt]) => (
              <tr key={label}><td>{label}</td>
                <td className="amt">{money(amt, d.spending?.currency)}</td></tr>
            ))}
          </tbody>
        </table>
      )}
      {Object.keys(d.income || {}).length > 0 && (
        <div className="quiet">Income recognized:{' '}
          {Object.entries(d.income).map(([c, v]) => money(v, c)).join('; ')}
          {(d.income_breakdown || []).length > 0 &&
            ` (withheld — ${d.income_breakdown.map(b => `${b.label} ${b.amount}`).join(' · ')})`}
        </div>
      )}
    </div>
  )
}

function Money({d, onAccount}) {
  const positionsBy = (d.positions || []).reduce((acc, p) => {
    (acc[p.account] = acc[p.account] || []).push(p); return acc
  }, {})
  return (
    <div className="card">
      {d.accounts.length === 0 && <div className="muted">No accounts yet. Add a statement below.</div>}
      {d.accounts.map(a => (
        <div key={a.account}>
          <div className="acct" onClick={() => onAccount(a.account)}>
            <span className="nm">{a.name}
              {a.liability && <span className="muted" style={{fontSize: 11}}> card</span>}
              {a.investment && <span className="muted" style={{fontSize: 11}}> investments</span>}
              <div className="src">
                {[a.institution, a.number].filter(Boolean).join(' ')}
                {a.holders?.length ? ' · ' + a.holders.join(', ') : ''}</div>
            </span>
            <span className="row">
              <span className="tiny">{a.liability ? 'owed' : ''} as of {a.as_of || '—'}</span>
              <span className={`dot g-${a.grade || 'unverified'}`} />
              <strong>{money(a.amount, a.currency)}</strong>
            </span>
          </div>
          {/* Holdings, with the valuation-class discipline made visible: every
              measured value shows its as-of, and a total that mixes vintages says so. */}
          {(positionsBy[a.account] || []).length > 0 && (
            <div style={{padding: '0 6px 12px'}}>
              {a.mixed_as_of && (
                <div className="tiny" style={{color: 'var(--warn)'}}>
                  These were measured on different dates — the total is only good as of {a.as_of}.
                </div>
              )}
              <table>
                <tbody>
                  {positionsBy[a.account].map(p => (
                    <tr key={p.instrument}>
                      <td>{p.instrument}
                        <div className="src">{p.units} units · as of {p.as_of} · {p.valuation_class}</div></td>
                      <td className="amt">{money(p.market_value, p.currency)}
                        {p.unrealized_gain && <div className="src">
                          unrealized {money(p.unrealized_gain, p.currency)}</div>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      ))}
    </div>
  )
}

function WhereItWent({d}) {
  const [bySub, setBySub] = useState(false)
  const src = bySub ? (d.spending_by_subcategory || {}) : (d.spending_by_category || {})
  const rows = Object.entries(src).sort((a, b) => Number(b[1]) - Number(a[1]))
  if (rows.length === 0) return null
  const top = Number(rows[0][1]) || 1
  const cur = d.spending?.currency || ''
  return (
    <div className="card">
      <div className="between">
        <h3>Where it went</h3>
        <button className="link" onClick={() => setBySub(!bySub)}>
          {bySub ? 'by category' : 'in more detail'}</button>
      </div>
      <table>
        <tbody>
          {rows.map(([label, amt]) => (
            <tr key={label}>
              <td>{label}<div className="bar">
                <span style={{width: `${Math.max(2, (Number(amt) / top) * 100)}%`}} /></div></td>
              <td className="amt">{money(amt, cur)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function AddDocuments({onDone}) {
  const [flash, setFlash] = useState('')
  const [log, setLog] = useState([])
  return (
    <div className="card">
      <div className="row">
        <label>Add statements: <input type="file" id="file" multiple /></label>
        <button className="ghost" onClick={async () => {
          const input = document.getElementById('file')
          const files = [...(input.files || [])]
          if (!files.length) return setFlash('Choose a file first.')
          setFlash(`Reading ${files.length} document(s)…`)
          const out = []
          for (const f of files) {
            try {
              const r = await api.upload(f)
              out.push(`${f.name} → ${r.action}${r.message ? ' · ' + r.message : ''}`)
            } catch (e) { out.push(`${f.name} → failed: ${e.message}`) }
            setLog([...out])
          }
          setFlash('Done.')
          input.value = ''
          onDone()
        }}>Upload</button>
        <span className="flash">{flash}</span>
      </div>
      {log.map((l, i) => <div className="src" key={i}>{l}</div>)}
    </div>
  )
}

export default function App() {
  const [d, setD] = useState(null)
  const [q, setQ] = useState(null)
  const [limit, setLimit] = useState(10)
  const [route, setRoute] = useState({name: 'home'})
  const [err, setErr] = useState('')

  const load = useCallback(async () => {
    try {
      const [ov, qs] = await Promise.all([api.overview(), api.questions(limit)])
      setD(ov); setQ(qs); setErr('')
    } catch (e) { setErr(e.message) }
  }, [limit])
  useEffect(() => { load() }, [load])

  const home = async () => { setRoute({name: 'home'}); await load() }
  const openQuestion = (question) => {
    if (question.kind === 'reconciliation' || question.kind === 'identity')
      return setRoute({name: 'held', docId: question.refs.doc_id})
    if (question.kind === 'transfer') return setRoute({name: 'transfer', q: question})
    return setRoute({name: 'merchant', q: question})
  }

  if (err) return <div className="card"><h3>I can't reach the ledger</h3>
    <div className="muted">{err}</div></div>
  if (!d) return <div className="card muted">Opening your vault…</div>

  if (route.name === 'account')
    return <AccountView id={route.id} onBack={home} />
  if (route.name === 'held')
    return <HeldDetail docId={route.docId} onBack={home} onDone={home} />
  if (route.name === 'transfer')
    return <TransferDetail q={route.q} onBack={home} onDone={home} />
  if (route.name === 'merchant')
    return <MerchantDetail q={route.q} onBack={home} onDone={home} />

  return (
    <>
      <Picture d={d} />
      <Questions data={q} onAnswer={load} onOpen={openQuestion}
                 onMore={() => setLimit(limit + 25)} />
      <Money d={d} onAccount={(id) => setRoute({name: 'account', id})} />
      <WhereItWent d={d} />
      <AddDocuments onDone={load} />
    </>
  )
}
