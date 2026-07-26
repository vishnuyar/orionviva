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
      {/* Slice 9a: money whose components are known and whose split is not. Its
          own line — folding it into spending would overstate, dropping it would
          understate, and both would be the confident-wrong answer. */}
      {Number(d.undecomposed?.total || 0) > 0 && (
        <div className="quiet">
          A further {money(d.undecomposed.total, d.spending?.currency)} across{' '}
          {d.undecomposed.count} payment{d.undecomposed.count > 1 ? 's' : ''} was
          part spending and part something else — I won't guess the split.
          {d.undecomposed.corroborates?.length > 0 &&
            ` Your ${d.undecomposed.corroborates.join(' or ')} would settle it.`}
        </div>
      )}
      {(d.ruled_accounts || []).length > 0 && (
        <div className="quiet">
          Things you've told me you hold or owe:{' '}
          {d.ruled_accounts.map(r => `${r.account.split(':').pop()} (${money(r.paid, r.currency)}${r.reliable_balance ? '' : ', balance unconfirmed'})`).join(', ')}.
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


/* Net worth (Slice 7). A CURVE, not a number with a date attached — so the
 * date is not a caption on the figure, it IS the figure's subject.
 *
 * Three things here that a bank app will not show you, each one a refusal to
 * bluff: every line's own measurement date (usually earlier than the point it
 * belongs to); the PROVABLE subtotal, backed by a document whose arithmetic
 * checks; and what is deliberately NOT counted, with the paperwork that would
 * settle it. A total that silently omits a mortgage is a lie of omission. */
function NetWorth() {
  const [nw, setNw] = useState(null)
  useEffect(() => { api.netWorth().then(setNw).catch(() => setNw(false)) }, [])
  if (nw === false || (nw && !nw.lines.length && !nw.missing.length)) return null
  if (!nw) return <div className="card muted">Working out what you're worth…</div>
  const stale = nw.oldest_input && nw.oldest_input !== nw.as_of
  return (
    <div className="card">
      <h3>What you're worth <span className="quiet">as of {nw.as_of}</span></h3>
      {!nw.complete && (
        <div className="why">
          Incomplete — your true net worth is <strong>lower</strong> than this.
        </div>
      )}
      {Object.entries(nw.by_currency).map(([cur, row]) => (
        <div key={cur} className="row" style={{marginTop: 8}}>
          <div className="grow">
            <div className="big">{money(row.net, cur)}</div>
            <div className="quiet">
              {money(row.assets, cur)} owned · {money(row.liabilities, cur)} owed
            </div>
            <div className="quiet">
              {money(row.provable, cur)} of it provable — a document attests it
              and the arithmetic checks
            </div>
          </div>
        </div>
      ))}
      {stale && (
        <div className="quiet" style={{marginTop: 8}}>
          Only as current as its oldest input: {nw.oldest_input}.
        </div>
      )}
      <table>
        <thead><tr><th>Account</th><th>Measured</th><th className="num">Amount</th></tr></thead>
        <tbody>
          {nw.lines.map(l => (
            <tr key={l.account}>
              <td>{l.account} {l.provable ? '' : <span className="quiet">· your word</span>}</td>
              <td className="quiet">{l.as_of}</td>
              <td className="num">{money(l.amount, l.currency)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      {nw.missing.map(m => (
        <div key={m.account} className="why">
          <strong>{m.account}</strong> is not counted — {m.why}. {m.would_fix} would settle it.
        </div>
      ))}
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
      <NetWorth />
      <Questions data={q} onAnswer={load} onOpen={openQuestion}
                 onMore={() => setLimit(limit + 25)} />
      <Money d={d} onAccount={(id) => setRoute({name: 'account', id})} />
      <WhereItWent d={d} />
      <AddDocuments onDone={load} />
    </>
  )
}
