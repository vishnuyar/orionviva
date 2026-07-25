import {useState} from 'react'
import {api, money} from './api'

/* The question queue — the page's spine (Slice 6.5 Move 2, surfaced in 6.7).
 *
 * Hybrid answering, as ruled: a question you can settle with one tap answers
 * INLINE; anything that needs context (a held statement, a merchant's
 * transactions) opens a focused detail view, so the most consequential decision
 * isn't squashed between quick ones.
 *
 * The ranking is the server's — by how much money answering moves. The surface
 * never re-sorts or re-computes; it only decides how a question reads. */

function Stake({q}) {
  return (
    <span className="stake">
      {money(q.amount, q.currency)}
      <span className="scope">
        {q.scope === 'one' ? 'settles this one'
          : `settles all ${q.count}${q.count > 1 ? ' — and future ones' : ''}`}
      </span>
    </span>
  )
}

function Answers({q, onAnswer, onOpen}) {
  const [busy, setBusy] = useState(false)
  const act = async (fn) => { setBusy(true); try { await fn(); await onAnswer() } finally { setBusy(false) } }

  if (q.kind === 'nature') {
    const m = q.refs.merchant
    return (
      <div className="row">
        <button disabled={busy} onClick={() => act(() => api.ruleNature(m, 'spending'))}>Money I spent</button>
        <button className="ghost" disabled={busy} onClick={() => act(() => api.ruleNature(m, 'transfer'))}>Moved between my accounts</button>
        <button className="ghost" disabled={busy} onClick={() => act(() => api.ruleNature(m, 'settlement'))}>Something I now own</button>
        <button className="link" onClick={() => onOpen(q)}>see the transactions</button>
      </div>
    )
  }
  if (q.kind === 'transfer') {
    const {movement, candidates} = q.refs
    return (
      <div className="row">
        <button disabled={busy} onClick={() => act(() => api.confirmTransfer(movement, candidates[0]))}>Yes — same money</button>
        <button className="ghost" disabled={busy} onClick={() => act(() => api.rejectTransfer(movement))}>No — that's spending</button>
        <button className="link" onClick={() => onOpen(q)}>compare both sides</button>
      </div>
    )
  }
  if (q.kind === 'identity') {
    const d = q.refs.doc_id
    return (
      <div className="row">
        <button disabled={busy} onClick={() => act(() => api.confirmIdentity({doc_id: d, decision: 'same'}))}>An account I have</button>
        <button className="ghost" disabled={busy} onClick={() => act(() => api.confirmIdentity({doc_id: d, decision: 'new'}))}>A new account</button>
      </div>
    )
  }
  if (q.kind === 'merchant') return <MerchantAnswer q={q} onAnswer={onAnswer} onOpen={onOpen} />
  // reconciliation — always needs the statement in front of you.
  return <div className="row"><button className="ghost" onClick={() => onOpen(q)}>Look at it</button></div>
}

/* Categories: the 16 suggestions, plus every category you've already used, plus
 * your own. Implicit storage as ruled — a category exists by being used, so
 * there is no new event and no schema to migrate. */
function CategoryPicker({categories, value, onChange}) {
  const [adding, setAdding] = useState(false)
  const [text, setText] = useState('')
  if (adding) return (
    <span className="row">
      <input type="text" autoFocus placeholder="name your category" value={text}
             onChange={e => setText(e.target.value)}
             onKeyDown={e => { if (e.key === 'Enter' && text.trim()) { onChange(text.trim()); setAdding(false) } }} />
      <button className="ghost" onClick={() => { if (text.trim()) { onChange(text.trim()); setAdding(false) } }}>Use it</button>
    </span>
  )
  return (
    <span className="row">
      <select value={value} onChange={e => e.target.value === '__new'
        ? setAdding(true) : onChange(e.target.value)}>
        {categories.map(c => <option key={c} value={c}>{c}</option>)}
        <option value="__new">+ add your own…</option>
      </select>
    </span>
  )
}

function MerchantAnswer({q, onAnswer, onOpen}) {
  const [cat, setCat] = useState('')
  const [busy, setBusy] = useState(false)
  const cats = q.refs.categories || []
  const chosen = cat || cats[0] || ''
  const perTransaction = q.scope === 'one'   // a peer: one Zelle is a gift, the next a loan
  return (
    <div className="row">
      <CategoryPicker categories={cats} value={chosen} onChange={setCat} />
      <button disabled={busy || !chosen} onClick={async () => {
        setBusy(true)
        try {
          if (perTransaction) {
            for (const key of (q.refs.movements || [])) await api.assignCategory(key, chosen)
          } else {
            await api.assignMerchant(q.refs.merchant, chosen)
          }
          await onAnswer()
        } finally { setBusy(false) }
      }}>{perTransaction ? 'Categorize these' : 'Categorize everywhere'}</button>
      {!perTransaction && <button className="link" onClick={() => onOpen(q)}>see the transactions</button>}
    </div>
  )
}

export default function Questions({data, onAnswer, onOpen, onMore}) {
  if (!data || !data.total) return null
  const {questions, tail, total} = data
  return (
    <div className="card ask">
      <div className="between">
        <h3>{total} thing{total > 1 ? 's' : ''} need{total > 1 ? '' : 's'} you</h3>
        <span className="tiny">most valuable first</span>
      </div>
      <div className="tiny" style={{marginBottom: 4}}>
        Nothing was guessed or dropped — these are the calls only you can make.
      </div>
      {questions.map(q => (
        <div className="q" key={q.id}>
          <div className="between">
            <div style={{flex: 1}}>
              <div className="text"><span className="kind">{q.kind}</span>{q.text}</div>
              <div className="why">{q.why}</div>
              <Answers q={q} onAnswer={onAnswer} onOpen={onOpen} />
            </div>
            <Stake q={q} />
          </div>
        </div>
      ))}
      {tail.count > 0 && (
        <div className="q">
          <span className="muted">…plus {tail.count} smaller item{tail.count > 1 ? 's' : ''} worth{' '}
            {money(tail.amount, questions[0]?.currency)} in total. </span>
          <button className="link" onClick={onMore}>show them</button>
        </div>
      )}
    </div>
  )
}
