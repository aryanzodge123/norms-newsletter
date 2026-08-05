import React, { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

const REDUCED =
  typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches

/* ------------------------------------------------------------------ hooks */

function useReveal(delay = 0) {
  const ref = useRef(null)
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (REDUCED) return el.classList.add('seen')
    const io = new IntersectionObserver(
      ([e]) => {
        if (e.isIntersecting) {
          setTimeout(() => el.classList.add('seen'), delay)
          io.unobserve(el)
        }
      },
      { threshold: 0.12 },
    )
    io.observe(el)
    return () => io.disconnect()
  }, [delay])
  return ref
}

function Reveal({ children, delay = 0, className = '', as: Tag = 'div' }) {
  const ref = useReveal(delay)
  return (
    <Tag ref={ref} className={`reveal ${className}`}>
      {children}
    </Tag>
  )
}

/* --------------------------------------------------------------- masthead */

function Masthead() {
  return (
    <header className="pad-x pt-7">
      <div className="mx-auto max-w-[1140px]">
        <div className="flex items-baseline justify-between gap-4">
          <span className="eyebrow impress hidden sm:block" style={{ animationDelay: '80ms' }}>
            Est. 2025
          </span>
          <span className="display impress text-[27px] sm:text-[31px]">Norm&rsquo;s Newsletter</span>
          <span className="eyebrow impress hidden sm:block" style={{ animationDelay: '160ms' }}>
            No. 057
          </span>
        </div>
        <hr className="rule-double rule-draw mt-3" style={{ animationDelay: '240ms' }} />
      </div>
    </header>
  )
}

/* ------------------------------------------------------------------- hero
   Block 1 (USP: main + supporting headline), block 2 (hero visual showing the
   product in real use), block 5 (one CTA). */

function Hero() {
  return (
    <section className="pad-x pt-16 pb-8 sm:pt-24">
      {/* Flex + wrap rather than a breakpoint: the columns sit side by side
          while both can hold their basis, and wrap the moment they cannot. */}
      <div className="mx-auto flex max-w-[1140px] flex-wrap items-center justify-center gap-x-16 gap-y-14">
        <div className="min-w-0 flex-[1_1_26rem]">
          <p className="eyebrow eyebrow-oxide impress" style={{ animationDelay: '420ms' }}>
            A paper, printed for one
          </p>

          {/* Sized to hold its two intended lines at 1440; the break is the
              point of the line, so it must not rag. The slash is drawn rather
              than underlined so it keeps the hand of a proof mark, and it takes
              its colour from the palette so it follows night paper. */}
          <h1
            className="display impress mt-5 text-[clamp(44px,5.6vw,74px)]"
            style={{ animationDelay: '520ms' }}
          >
            Read less.
            <br />
            Miss{' '}
            <span className="relative whitespace-nowrap">
              nothing.
              <svg
                aria-hidden="true"
                viewBox="0 0 300 12"
                preserveAspectRatio="none"
                className="absolute left-0 w-full"
                /* em, not px: the headline clamps from 74px to 44px, and a
                   fixed offset that clears the descender at the top size
                   rides up into the word at the bottom one. */
                style={{ color: 'var(--oxide)', bottom: '-0.085em', height: '0.13em' }}
              >
                <path
                  d="M2 8.5C58 3.5 126 2.5 298 5.5"
                  fill="none"
                  stroke="currentColor"
                  strokeWidth="2.5"
                  strokeLinecap="round"
                />
              </svg>
            </span>
          </h1>

          <p
            className="dropcap impress mt-7 max-w-[47ch] font-display text-[19px] leading-[1.62] text-[var(--ink-soft)]"
            style={{ animationDelay: '660ms' }}
          >
            From headline to context. Shape your newsletter using the stories you track, explained
            from the roots up. Turn daily clutter into deep, meaningful insights without any of the
            noise.
          </p>

          <div className="impress mt-10" style={{ animationDelay: '780ms' }}>
            <a href="#build" className="btn-oxide inline-block px-8 py-3.5 text-[15px]">
              Build my edition
            </a>
            <p className="eyebrow mt-4">
              Six weeks free &middot; no card &middot; your first edition lands tomorrow
            </p>
          </div>
        </div>

        <div className="impress min-w-0 flex-[0_1_21rem]" style={{ animationDelay: '620ms' }}>
          <PhoneInUse />
        </div>
      </div>
    </section>
  )
}

/* The product as it is actually used: a recording of the committed prototype,
   walked end to end. The device frame is part of the recording, so nothing
   wraps it. A GIF cannot be paused, so reduced-motion users get frame one. */
function PhoneInUse() {
  return (
    <figure className="relative mx-auto w-full max-w-[324px]">
      {REDUCED ? (
        <img
          src="/app-walkthrough-poster.jpg"
          width="434"
          height="878"
          alt="The Norm's Newsletter app showing today's edition."
          className="block h-auto w-full"
          style={{ filter: 'drop-shadow(0 30px 55px rgb(0 0 0 / 0.32))' }}
        />
      ) : (
        <video
          width="434"
          height="878"
          autoPlay
          loop
          muted
          playsInline
          poster="/app-walkthrough-poster.jpg"
          aria-label="The Norm's Newsletter app: today's edition, a story opened to its background, what happened and why it matters, the archive of every edition, and the night paper switched on."
          className="block h-auto w-full"
          style={{ filter: 'drop-shadow(0 30px 55px rgb(0 0 0 / 0.32))' }}
        >
          <source src="/app-walkthrough.webm" type="video/webm" />
          <source src="/app-walkthrough.mp4" type="video/mp4" />
        </video>
      )}
      <figcaption className="eyebrow mt-5 text-center">
        Recorded from the app &middot; No. 056
      </figcaption>
    </figure>
  )
}

/* Kept for reference: the hand-built mock the recording replaced. */
function PhoneMockUnused() {
  return (
    <div className="relative mx-auto w-full max-w-[352px]">
      <div
        className="sheet relative overflow-hidden rounded-[38px] p-3"
        style={{ boxShadow: '0 30px 60px -30px rgb(0 0 0 / 0.45)' }}
      >
        <div
          className="relative overflow-hidden rounded-[28px] px-5 pt-9 pb-6"
          style={{ background: 'var(--paper)' }}
        >
          <div
            className="absolute top-3 left-1/2 h-[5px] w-[86px] -translate-x-1/2 rounded-full"
            style={{ background: 'var(--rule)' }}
          />
          <div className="flex items-baseline justify-between">
            <span className="eyebrow">Sunday, Aug 3</span>
            <span className="eyebrow eyebrow-oxide">No. 057</span>
          </div>
          <hr className="mt-2 border-0 border-t" style={{ borderColor: 'var(--ink)' }} />

          <p className="eyebrow mt-5">World &middot; 4 sources</p>
          <h3 className="display mt-1.5 text-[23px]">
            Trump calls off the Iran strikes, demanding a Hormuz deal in days
          </h3>
          <p className="mt-2.5 text-[13.5px] leading-[1.55] text-[var(--ink-soft)]">
            The order was pulled back with aircraft already staged.
          </p>

          <hr className="mt-5 border-0 border-t" style={{ borderColor: 'var(--rule-faint)' }} />
          <p className="eyebrow mt-4">Technology &middot; 3 sources</p>
          <h4 className="display mt-1.5 text-[17px]">
            DeepMind disbands the AlphaFold team and moves it onto Gemini
          </h4>

          <hr className="mt-5 border-0 border-t" style={{ borderColor: 'var(--rule-faint)' }} />
          <p className="eyebrow mt-4">Politics &middot; 5 sources</p>
          <h4 className="display mt-1.5 text-[17px]">
            US sanctions two Iranian firms over a Bitcoin scheme
          </h4>

          <div
            className="mt-6 flex items-center justify-between rounded-full px-4 py-2.5"
            style={{ background: 'var(--paper-raised)', border: '1px solid var(--rule)' }}
          >
            <span className="eyebrow eyebrow-oxide">&#9654; Listen &middot; 8:42</span>
            <span className="eyebrow">3 of 6</span>
          </div>
        </div>
      </div>
      <p className="eyebrow mt-4 text-center">7:15 am &middot; read before the train</p>
    </div>
  )
}

/* --------------------------------------------------------------- benefits
   Block 3. Benefit leads, the feature backs it up. */

const BENEFITS = [
  [
    'Outsource the curation.',
    'Our system scores every story on foundational relevance, filtering out duplicate coverage so you never have to waste time deciding what deserves your attention.',
    'Total coverage. Filtered continuously.',
  ],
  [
    'A definitive finish line.',
    'Your edition is a complete experience, not an open-ended obligation. By choosing exactly how long or brief you want your package to be, you skip the infinite feeds, endless rabbit holes, and algorithmic traps, leaving you with a focused brief designed to be read, understood, and finished.',
    'Tailored length. Zero infinite feeds.',
  ],
  [
    'Assembled for your routine.',
    'Content is evaluated around the clock for genuine impact and importance. Instead of interrupting your day with constant alerts, your custom edition is quietly built and delivered at the exact moment you choose to read.',
    'On-demand delivery. Matched to your schedule.',
  ],
  [
    'Context you can verify.',
    'We translate raw, scattered updates into clear, foundational narratives without taking shortcuts. Every single story includes direct links back to the original source materials, putting total transparency at your fingertips.',
    'Chronicled from original sources.',
  ],
]

function Benefits() {
  return (
    <section className="pad-x py-20">
      <div className="mx-auto max-w-[1140px]">
        <Reveal>
          <p className="label-rule eyebrow">Why it works</p>
        </Reveal>
        <div className="mt-12 flex flex-wrap gap-x-14 gap-y-12">
          {BENEFITS.map(([benefit, why, feature], i) => (
            <Reveal key={benefit} delay={i * 90} className="min-w-0 flex-[1_1_22rem]">
              <h3 className="display max-w-[20ch] text-[clamp(24px,3vw,32px)]">{benefit}</h3>
              <p className="mt-3 max-w-[46ch] text-[15px] leading-[1.62] text-[var(--ink-soft)]">
                {why}
              </p>
              <p className="eyebrow eyebrow-oxide mt-4">{feature}</p>
            </Reveal>
          ))}
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------------------- the topics screen
   Ported from prototypes/App Interface.dc.html, the More -> Topics screen.
   Data tables, copy, pixel values and the pointer-driven weight control are
   the prototype's. Colours go through the --tod palette so the section still
   re-lights with the delivery dial; NS_INKS stay literal because they are the
   per-section inks, not theme colours.

   The export marks everything up as clickable divs, as design exports do.
   That part is not carried over: rows and controls are real buttons, the
   slider is a role="slider" with arrow keys, and the overlays close on Escape. */

const NS_TOPICS = [
  { id: 'politics', name: 'Politics', meta: '3 today' },
  { id: 'world', name: 'World', meta: '3 today' },
  { id: 'business', name: 'Business & markets', meta: '2 today' },
  { id: 'ai', name: 'Artificial intelligence', meta: '2 today' },
  { id: 'tech', name: 'Technology', meta: '2 today' },
  { id: 'science', name: 'Science', meta: '2 today' },
  { id: 'climate', name: 'Climate', meta: '1 today' },
  { id: 'health', name: 'Health', meta: '1 today' },
  { id: 'culture', name: 'Culture', meta: '1 today' },
  { id: 'sports', name: 'Sport', meta: '—' },
  { id: 'media', name: 'Media', meta: '1 today' },
  { id: 'law', name: 'Law & courts', meta: '1 today' },
  { id: 'education', name: 'Education', meta: '1 today' },
  { id: 'energy', name: 'Energy', meta: '1 today' },
  { id: 'space', name: 'Space', meta: '1 today' },
  { id: 'money', name: 'Personal finance', meta: '1 today' },
  { id: 'entertainment', name: 'Entertainment', meta: '1 today' },
  { id: 'travel', name: 'Travel', meta: '—' },
  { id: 'food', name: 'Food & drink', meta: '—' },
  { id: 'housing', name: 'Housing & real estate', meta: '1 today' },
]

const NS_BANDS = [
  { max: 2, label: 'Nice to have', note: 'Runs only when the story is big enough to lead the edition.' },
  { max: 4, label: 'Now and then', note: 'A story when something genuinely moves. Quiet weeks stay quiet.' },
  { max: 6, label: 'Most mornings', note: 'A story or two in most editions, in your running order.' },
  { max: 8, label: 'Standing order', note: 'The full section every morning, however the day went.' },
  { max: 10, label: 'Keep me current', note: 'Everything Norm files here, plus the Sunday look-back on it.' },
]

const NS_INKS = ['#3F6A50', '#8A4B2A', '#2F4F6B', '#6B3F5E', '#A8762A', '#4A6B3F', '#7A3B3B', '#4B4A63']

const nsBand = (v) => NS_BANDS.find((b) => v <= b.max) || NS_BANDS[NS_BANDS.length - 1]
const topicOf = (id) => NS_TOPICS.find((t) => t.id === id)
const inkOf = (id) =>
  NS_INKS[Math.max(0, NS_TOPICS.findIndex((t) => t.id === id)) % NS_INKS.length]

/* The length setting. In the prototype this lives on the newsletter Settings
   screen rather than Topics, but the Topics screen already states its result
   ("Length: about 11 stories a morning"), so the control sits with it here. */
const NS_LEN = [
  { label: 'Front page', stories: 5, note: 'The headline of the day and the glance. Nothing else lands on your phone.' },
  { label: 'Short', stories: 8, note: 'The glance, and the stories that clearly cleared the bar.' },
  { label: 'As filed', stories: 11, note: 'The edition the way Norm files it — every section that ran, in your order.' },
  { label: 'Long', stories: 16, note: 'Everything scored, and Briefly in full rather than as a strip of links.' },
  { label: 'Everything', stories: 20, note: 'Every cluster Norm kept, including the sections he held back for thinness.' },
]
const LEN_DEFAULT = 2 // "As filed"

/* Largest remainder, so the segments really do total 100 and the bar is full. */
function shares(sel, wt) {
  const total = sel.reduce((s, id) => s + wt[id], 0) || 1
  const raw = sel.map((id) => (wt[id] / total) * 100)
  const out = raw.map(Math.floor)
  const short = 100 - out.reduce((a, b) => a + b, 0)
  raw
    .map((v, i) => [v - Math.floor(v), i])
    .sort((a, b) => b[0] - a[0])
    .slice(0, short)
    .forEach(([, i]) => out[i]++)
  return out
}

/* The prototype's control: a track, ten ticks, a fill and a mark, driven by
   pointer position rather than a native input. */
function WeightSlider({ value, onChange }) {
  const ref = useRef(null)
  const set = (e) => {
    const r = ref.current.getBoundingClientRect()
    const f = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width))
    onChange(1 + Math.round(f * 9))
  }
  const key = (e) => {
    const d = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }[e.key]
    if (d) {
      e.preventDefault()
      // Functional, not value + d: key repeat fires faster than React commits,
      // so reading the closed-over value makes held arrows stall.
      onChange((cur) => cur + d)
    } else if (e.key === 'Home') onChange(1)
    else if (e.key === 'End') onChange(10)
  }
  const p = ((value - 1) / 9) * 100
  return (
    <div
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-label="Weight"
      aria-valuemin={1}
      aria-valuemax={10}
      aria-valuenow={value}
      aria-valuetext={`${value} of 10, ${nsBand(value).label}`}
      onKeyDown={key}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture?.(e.pointerId)
        set(e)
      }}
      onPointerMove={(e) => e.buttons && set(e)}
      className="ns-dial"
    >
      <span className="ns-dial-track" />
      {Array.from({ length: 10 }, (_, i) => (
        <span
          key={i}
          className="ns-dial-tick"
          style={{ left: `calc(${(i / 9) * 100}% - 0.5px)`, background: i + 1 <= value ? 'var(--oxide)' : 'var(--rule)' }}
        />
      ))}
      <span className="ns-dial-fill" style={{ width: `${p}%` }} />
      <span className="ns-dial-mark" style={{ left: `calc(${p}% - 11px)` }} />
    </div>
  )
}

/* Five stops rather than ten, and the index comes from round(f * 4). Same
   track-ticks-fill-mark construction as the weight control. */
function LengthSlider({ index, onChange }) {
  const ref = useRef(null)
  const set = (e) => {
    const r = ref.current.getBoundingClientRect()
    const f = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width))
    onChange(Math.round(f * 4))
  }
  const key = (e) => {
    const d = { ArrowLeft: -1, ArrowDown: -1, ArrowRight: 1, ArrowUp: 1 }[e.key]
    if (d) {
      e.preventDefault()
      onChange((cur) => cur + d)
    } else if (e.key === 'Home') onChange(0)
    else if (e.key === 'End') onChange(4)
  }
  const p = (index / 4) * 100
  return (
    <div
      ref={ref}
      role="slider"
      tabIndex={0}
      aria-label="Length"
      aria-valuemin={0}
      aria-valuemax={4}
      aria-valuenow={index}
      aria-valuetext={`${NS_LEN[index].label}, about ${NS_LEN[index].stories} stories`}
      onKeyDown={key}
      onPointerDown={(e) => {
        e.currentTarget.setPointerCapture?.(e.pointerId)
        set(e)
      }}
      onPointerMove={(e) => e.buttons && set(e)}
      className="ns-dial"
    >
      <span className="ns-dial-track" />
      {NS_LEN.map((_, i) => (
        <span
          key={i}
          className="ns-len-tick"
          style={{
            left: `calc(${(i / 4) * 100}% - 0.5px)`,
            background: i <= index ? 'var(--oxide)' : 'var(--rule)',
          }}
        />
      ))}
      <span className="ns-dial-fill" style={{ width: `${p}%` }} />
      <span className="ns-dial-mark" style={{ left: `calc(${p}% - 11px)` }} />
    </div>
  )
}

function TopicStudio() {
  const [sel, setSel] = useState(['politics', 'world', 'ai', 'tech', 'climate'])
  const [wt, setWt] = useState({ politics: 8, world: 7, ai: 6, tech: 4, climate: 2 })
  const [editing, setEditing] = useState(null)
  const [adding, setAdding] = useState(false)
  const [dragId, setDragId] = useState(null)
  const [lenI, setLenI] = useState(LEN_DEFAULT)
  const len = NS_LEN[lenI]

  const listRef = useRef(null)
  const positions = useRef(new Map())
  const overlayRef = useRef(null)

  const pcts = useMemo(() => shares(sel, wt), [sel, wt])
  const rows = sel.map((id, i) => ({
    id,
    name: topicOf(id).name,
    ink: inkOf(id),
    w: wt[id],
    band: nsBand(wt[id]).label,
    pct: pcts[i],
    count: Math.max(0, Math.round((pcts[i] / 100) * len.stories)),
  }))
  const rest = NS_TOPICS.filter((t) => !sel.includes(t.id))
  const lead = rows[0]

  // FLIP, so a reorder travels instead of jumping.
  useLayoutEffect(() => {
    const el = listRef.current
    if (!el || REDUCED) return
    el.querySelectorAll('[data-nsid]').forEach((row) => {
      const now = row.getBoundingClientRect().top
      const was = positions.current.get(row.dataset.nsid)
      if (was !== undefined && Math.abs(was - now) > 0.5) {
        row.style.transition = 'none'
        row.style.transform = `translateY(${was - now}px)`
        requestAnimationFrame(() => {
          row.style.transition = ''
          row.style.transform = ''
        })
      }
      positions.current.set(row.dataset.nsid, now)
    })
  })

  useEffect(() => {
    if (!editing && !adding) return
    overlayRef.current?.focus()
    const esc = (e) => {
      if (e.key === 'Escape') {
        setEditing(null)
        setAdding(false)
      }
    }
    addEventListener('keydown', esc)
    return () => removeEventListener('keydown', esc)
  }, [editing, adding])

  const setWeight = (id, v) =>
    setWt((p) => ({
      ...p,
      [id]: Math.max(1, Math.min(10, typeof v === 'function' ? v(p[id]) : v)),
    }))
  const remove = (id) => {
    if (sel.length <= 3) return // the prototype's floor
    setSel((s) => s.filter((x) => x !== id))
    setEditing(null)
  }
  const add = (id) => {
    setSel((s) => [...s, id])
    setWt((p) => ({ ...p, [id]: 6 }))
    setAdding(false)
    setEditing(id)
  }

  /* Drag to reorder: hit-test the row under the pointer, as the prototype does. */
  const dragDown = (id) => (e) => {
    e.currentTarget.setPointerCapture?.(e.pointerId)
    setDragId(id)
  }
  const dragMove = (e) => {
    if (!dragId) return
    const nodes = [...listRef.current.querySelectorAll('[data-nsid]')]
    const over = nodes.find((n) => {
      const r = n.getBoundingClientRect()
      return e.clientY >= r.top && e.clientY <= r.bottom
    })
    if (!over || over.dataset.nsid === dragId) return
    setSel((s) => {
      const from = s.indexOf(dragId)
      const to = s.indexOf(over.dataset.nsid)
      if (from < 0 || to < 0) return s
      const next = s.slice()
      next.splice(to, 0, next.splice(from, 1)[0])
      return next
    })
  }
  const dragUp = () => setDragId(null)

  const focus = editing ? { ...rows.find((r) => r.id === editing), band: nsBand(wt[editing]) } : null

  return (
    <section id="topics" className="pad-x py-20">
      <div className="mx-auto max-w-[1140px]">
        <Reveal>
          <p className="label-rule eyebrow">Set your front page</p>
        </Reveal>

        <div className="mt-12 flex flex-wrap items-start gap-x-16 gap-y-12">
          {/* LEFT: what the weights actually mean */}
          <Reveal delay={80} className="min-w-0 flex-[1_1_23rem]">
            <h2 className="display max-w-[16ch] text-[clamp(30px,4.6vw,50px)]">
              One paper, split the way you weighted it.
            </h2>
            <p className="mt-5 max-w-[46ch] text-[16px] leading-[1.62] text-[var(--ink-soft)]">
              This is the app&rsquo;s own Topics screen, not a picture of it. Open a section to set
              how much of it you want, drag to change the running order, and the paper on the right
              re-divides as you go.
            </p>

            <p className="eyebrow eyebrow-oxide mt-10">What a weight means</p>
            <ol className="mt-4 border-t" style={{ borderColor: 'var(--rule)' }}>
              {NS_BANDS.map((b) => {
                const on = focus && focus.band.label === b.label
                return (
                  <li
                    key={b.label}
                    className="border-b py-3.5 transition-[opacity,padding] duration-300"
                    style={{
                      borderColor: 'var(--rule-faint)',
                      opacity: !focus || on ? 1 : 0.42,
                      paddingLeft: on ? 12 : 0,
                      borderLeft: on ? `2px solid ${focus.ink}` : '2px solid transparent',
                    }}
                  >
                    <div className="flex items-baseline justify-between gap-4">
                      <span className="font-display text-[18px] font-medium">{b.label}</span>
                      <span className="eyebrow">
                        {b.max - 1 || 1}&ndash;{b.max}
                      </span>
                    </div>
                    <p className="mt-1 max-w-[42ch] text-[14px] leading-[1.55] text-[var(--muted)]">
                      {b.note}
                    </p>
                  </li>
                )
              })}
            </ol>

            <div className="sheet mt-8 px-6 py-5">
              <p className="eyebrow">{focus ? 'Editing' : 'As it stands'}</p>
              {focus ? (
                <>
                  <p className="display mt-2 text-[26px]">{focus.name}</p>
                  <p className="mt-1.5 text-[14.5px] text-[var(--ink-soft)]">
                    <span style={{ color: focus.ink }}>&#9679;</span> {wt[editing]} of 10 &middot;{' '}
                    {focus.band.label} &middot; about {focus.count} of {len.stories} stories
                  </p>
                </>
              ) : (
                <>
                  <p className="display mt-2 text-[26px]">
                    {lead ? `${lead.name} leads at ${lead.pct}%` : 'Nothing followed yet'}
                  </p>
                  <p className="mt-1.5 text-[14.5px] text-[var(--ink-soft)]">
                    {sel.length} sections &middot; {len.label.toLowerCase()} &middot; about {len.stories} stories a morning
                  </p>
                </>
              )}
            </div>
          </Reveal>

          {/* RIGHT: the prototype's Topics screen */}
          <Reveal delay={160} className="min-w-0 flex-[1_1_23rem]">
            <div className="sheet relative overflow-hidden px-6 py-7 sm:px-7">
              <h3 className="display text-[26px]">Topics</h3>
              <p className="mt-1.5 text-[14px] leading-[1.6] text-[var(--ink-soft)]">
                One paper, split the way you weighted it.
              </p>

              <h4 className="ns-head">The whole edition</h4>
              <div className="ns-bar">
                {rows.map((r) => (
                  <span
                    key={r.id}
                    className="ns-seg"
                    style={{ width: `${r.pct}%`, background: r.ink }}
                  />
                ))}
              </div>
              <div className="ns-barcap">
                <span>{lead ? `${lead.name} leads at ${lead.pct}%` : 'Nothing followed yet'}</span>
                <span>100% of the paper</span>
              </div>

              <h4 className="ns-head" style={{ margin: '24px 0 2px' }}>
                In your paper
              </h4>
              <ol ref={listRef}>
                {rows.map((r) => (
                  <li key={r.id} data-nsid={r.id} className="ns-row-wrap">
                    <button
                      type="button"
                      className="ns-row"
                      data-drag={dragId === r.id}
                      onClick={() => setEditing(r.id)}
                      onPointerMove={dragMove}
                      onPointerUp={dragUp}
                      onPointerCancel={dragUp}
                      aria-label={`${r.name}, ${r.w} of 10, ${r.band}, ${r.pct}%`}
                    >
                      <span className="flex min-w-0 flex-1 flex-col gap-[3px]">
                        <span className="flex items-center gap-2">
                          <span className="text-[14.5px] font-medium">{r.name}</span>
                          <span className="ns-dot" style={{ background: r.ink }} />
                        </span>
                        <span className="ns-band">{r.band}</span>
                      </span>
                      <span className="font-display text-[19px]">{r.pct}%</span>
                      <span
                        className="ns-grip"
                        aria-hidden="true"
                        onPointerDown={dragDown(r.id)}
                        onClick={(e) => e.stopPropagation()}
                      >
                        &#8942;&#8942;
                      </span>
                    </button>
                  </li>
                ))}
              </ol>

              <button type="button" className="ns-add" onClick={() => setAdding(true)}>
                Add a topic
              </button>

              <p className="ns-foot" style={{ margin: '14px 0 0' }}>
                Drag a section to change the running order.
              </p>

              <h4 className="ns-head" style={{ margin: '26px 0 2px' }}>
                Length
              </h4>
              <div className="pt-3.5">
                <div className="flex items-end justify-between gap-3">
                  <span className="display text-[27px] leading-[1.1]">{len.label}</span>
                  <span className="ns-len-est">about {len.stories} stories</span>
                </div>
                <LengthSlider
                  index={lenI}
                  onChange={(v) =>
                    setLenI((c) => Math.max(0, Math.min(4, typeof v === 'function' ? v(c) : v)))
                  }
                />
                <div className="ns-ends">
                  <span>Biggest updates only</span>
                  <span>Everything going on</span>
                </div>
                <p className="ns-len-note">{len.note}</p>
              </div>
              <p className="ns-foot">
                Length changes the paper, not the archive.
                <br />
                Everything Norm filed stays searchable.
              </p>

              {/* Weight editor. In the prototype this is scoped to the phone;
                  here it is scoped to this panel. */}
              {focus && (
                <div className="ns-overlay" role="dialog" aria-modal="true" aria-label={`Weight for ${focus.name}`}>
                  <button className="ns-scrim" aria-label="Close" onClick={() => setEditing(null)} />
                  <div className="ns-sheet" ref={overlayRef} tabIndex={-1}>
                    <div className="ns-sheet-head">
                      <span>{focus.name}</span>
                      <span className="ns-sheet-meta">{topicOf(editing).meta}</span>
                    </div>
                    <h5 className="display mt-3 text-[25px] leading-[1.2]">
                      How much {focus.name} do you want?
                    </h5>
                    <p className="mt-1.5 text-[13px] leading-[1.55] text-[var(--ink-soft)]">
                      One means only when it&rsquo;s big enough to lead. Ten means keep me current.
                    </p>
                    <div className="mt-4 flex items-end justify-between gap-3">
                      <span className="flex items-baseline gap-2">
                        <span className="display text-[50px] leading-none tracking-[-0.03em]">
                          {wt[editing]}
                        </span>
                        <span className="eyebrow normal-case">of 10</span>
                      </span>
                      <span className="ns-bandtag" style={{ color: focus.ink }}>
                        {focus.band.label}
                      </span>
                    </div>
                    <WeightSlider value={wt[editing]} onChange={(v) => setWeight(editing, v)} />
                    <div className="ns-ends">
                      <span>Nice to have</span>
                      <span>Keep me current</span>
                    </div>
                    <p className="ns-note">{focus.band.note}</p>
                    <button type="button" className="ns-cta" onClick={() => setEditing(null)}>
                      Save
                    </button>
                    <button
                      type="button"
                      className="ns-second"
                      onClick={() => remove(editing)}
                      disabled={sel.length <= 3}
                    >
                      {sel.length <= 3 ? 'Three sections minimum' : 'Remove from my paper'}
                    </button>
                  </div>
                </div>
              )}

              {/* Add sheet */}
              {adding && (
                <div className="ns-overlay" role="dialog" aria-modal="true" aria-label="More topics">
                  <button className="ns-scrim" aria-label="Close" onClick={() => setAdding(false)} />
                  <div className="ns-sheet" ref={overlayRef} tabIndex={-1}>
                    <div className="ns-sheet-head">
                      <span>More topics</span>
                      <span className="ns-sheet-meta">{rest.length} left</span>
                    </div>
                    <p className="ns-note" style={{ minHeight: 0, margin: '12px 0 0' }}>
                      Every section Norm files is already on your front page.
                      <br />
                      Adding a section changes what leads. It never adds a second edition.
                    </p>
                    <ul className="ns-addlist">
                      {rest.map((t) => (
                        <li key={t.id}>
                          <button type="button" className="ns-addrow" onClick={() => add(t.id)}>
                            <span className="flex items-center gap-2">
                              <span className="ns-dot" style={{ background: inkOf(t.id) }} />
                              <span className="text-[14.5px] font-medium">{t.name}</span>
                            </span>
                            <span className="ns-band">{t.meta}</span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </div>
                </div>
              )}
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  )
}

/* ------------------------------------------- reinforcing statement (block 1) */

function Reinforce() {
  return (
    <section className="pad-x py-16">
      <div className="mx-auto max-w-[1140px]">
        <Reveal>
          <div
            className="border-y py-14 text-center"
            style={{ borderColor: 'var(--rule)' }}
          >
            <p className="display mx-auto max-w-[22ch] text-[clamp(28px,4.4vw,46px)]">
              However you weight it, it is still one paper, and it still ends.
            </p>
          </div>
        </Reveal>
      </div>
    </section>
  )
}

/* ------------------------------------------------------- the delivery dial
   The prototype's delivery-time step. Moving it re-lights the entire page:
   the palette travels from dawn to the prototype's Night paper. */

const STOPS = [
  ['5:30 am', 'dawn', 'Before the house wakes'],
  ['7:15 am', 'morning', 'On the commute, still warm'],
  ['12:30 pm', 'day', 'Read over lunch'],
  ['6:00 pm', 'dusk', 'The train home'],
  ['9:40 pm', 'night', 'The night paper, in the dark palette'],
]

function DeliveryDial({ idx, setIdx }) {
  const [time, tod, note] = STOPS[idx]
  const t = idx / (STOPS.length - 1)
  // The orb rides a real arc: up over the morning, down into the night.
  const x = 8 + t * 84
  const y = 74 - Math.sin(t * Math.PI) * 54

  return (
    <section id="delivery" className="pad-x py-20">
      <div className="mx-auto max-w-[1140px]">
        <Reveal>
          <p className="label-rule eyebrow">When it lands</p>
        </Reveal>
        <div className="mt-12 flex flex-wrap items-center gap-x-16 gap-y-12">
          <Reveal className="min-w-0 flex-[1_1_24rem]">
            <h2 className="display max-w-[16ch] text-[clamp(30px,4.6vw,50px)]">
              Written overnight. Held until the moment you read.
            </h2>
            <p className="mt-5 max-w-[46ch] text-[16px] leading-[1.62] text-[var(--ink-soft)]">
              Drag the dial. The page changes with it, because the app does too: pick an evening and
              you get the night paper, in the dark palette, the way you would actually be holding
              it.
            </p>
            <p className="eyebrow mt-6">One nudge a day, nothing else</p>
          </Reveal>

          <Reveal delay={120} className="min-w-0 flex-[1_1_22rem]">
            <div className="sheet px-7 py-8">
              <svg viewBox="0 0 100 80" className="h-24 w-full" aria-hidden="true">
                <path
                  d="M8 74 Q50 4 92 74"
                  fill="none"
                  stroke="var(--rule)"
                  strokeWidth="1"
                  strokeDasharray="3 4"
                />
                <line x1="0" y1="74" x2="100" y2="74" stroke="var(--rule)" strokeWidth="1" />
                <circle
                  className="sky-orb"
                  cx={x}
                  cy={y}
                  r={tod === 'night' ? 4 : 5.5}
                  fill="var(--oxide)"
                  style={{ transition: 'cx 900ms cubic-bezier(.4,0,.2,1), cy 900ms cubic-bezier(.4,0,.2,1), r 900ms ease' }}
                />
              </svg>

              <p className="display mt-3 text-[clamp(40px,6vw,60px)] text-[var(--oxide)] tabular-nums">
                {time}
              </p>
              <p className="eyebrow mt-1">{note}</p>

              <input
                type="range"
                className="dial mt-8"
                min="0"
                max={STOPS.length - 1}
                value={idx}
                onChange={(e) => setIdx(Number(e.target.value))}
                aria-label="Delivery time"
              />
              <div className="eyebrow mt-1.5 flex justify-between">
                <span>5 am</span>
                <span>12 pm</span>
                <span>10 pm</span>
              </div>
            </div>
          </Reveal>
        </div>
      </div>
    </section>
  )
}

/* ----------------------------------------------------------------- the press
   Scroll-driven: the night's raw wire narrows to the stories that run.

   35 is the enabled count in config/sources.yaml (37 entries, 2 held back for
   missing credentials). 149 and 112 are the per-day means of items_ingested
   and clusters_considered across the 17 published editions, No. 43 to No. 59.
   Both true means land on a half (148.5 and 112.5), so they are recorded here
   rather than left to look arbitrary. 5 to 20 is the reader's own length
   setting, and matches NS_LEN in the Topics section above. */

const STAGES = [
  ['35', 'sources read', 'Everything Norm subscribes to, checked every hour.'],
  ['149', 'items filed', 'Most of it is the same story told by different desks.'],
  ['112', 'stories left', 'Duplicates clustered, the rest scored against your weights.'],
  ['5-20', 'stories run', 'As many as you asked for. You set the length, and the page still ends.'],
]

/* ---- the composing floor -------------------------------------------------
   The stone. Wire copy lands, duplicates stack behind a lead, and the
   survivors lock into a forme as lines of type. One element does all four
   stages, so nothing is created or destroyed as the night runs: a 240x3 block
   that is only ever transformed.

   Solid, not a bordered card. This shape is scaled from 1.4px wide to 240px,
   and a scaled border is a scaled border: the hairline would vanish at one end
   of that range and become a slab at the other. */

const SLIP_N = 40
const LEADS = 12 // stacks at stage 3, and the lines of the finished page
const SLIP_W = 240
const SLIP_H = 3

function mulberry32(a) {
  return () => {
    a = (a + 0x6d2b79f5) | 0
    let t = Math.imul(a ^ (a >>> 15), 1 | a)
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

// Fixed seed. The scatter is disorder, not randomness: it has to be the same
// heap on every reload, or the section changes shape when you scroll back.
const SLIPS = (() => {
  const r = mulberry32(20260805)
  return Array.from({ length: SLIP_N }, (_, i) => ({
    lead: i < LEADS,
    cluster: i % LEADS,
    depth: Math.floor(i / LEADS),
    sx: r(),
    sy: r(),
    spin: r() * 16 - 8, // degrees, loose on the stone
    tilt: r() * 4 - 2, // degrees, once squared into a stack
    jog: r() * 18 - 9, // the stacks do not sit on a ruled line
    measure: 0.55 + r() * 0.45, // line length in the forme
  }))
})()

/* Transform per slip per stage. Pure: no reads, no layout, one string. */
function slipTransform(s, i, stage, w, h) {
  const at = (x, y, rot, sx, sy) =>
    `translate(${x.toFixed(1)}px, ${(y - SLIP_H / 2).toFixed(1)}px) rotate(${rot.toFixed(1)}deg) scale(${sx.toFixed(4)}, ${sy})`

  // 2: a chit of copy, 18 x 9.
  const chit = [0.075, 3]
  const scatterX = 8 + s.sx * Math.max(0, w - 30)
  const scatterY = 16 + s.sy * Math.max(0, h - 32)

  const colGap = w / LEADS
  const stackX = colGap * (s.cluster + 0.5) - 9 + s.depth * 3
  const stackY = h / 2 + s.jog - s.depth * 2.5

  const x0 = (w - SLIP_W) / 2
  const leading = 12
  const top = (h - LEADS * leading) / 2 + 10

  switch (stage) {
    case 0: // every source Norm subscribes to, standing as a tick
      return at(10 + (i * Math.max(0, w - 20)) / (SLIP_N - 1), h / 2, 0, 0.006, 10)
    case 1: // the night's copy, heaped
      return at(scatterX, scatterY, s.spin, ...chit)
    case 2: // clustered: duplicates squared up behind a lead
      return at(stackX, stackY, s.tilt, ...chit)
    default: // locked into the forme, or dropped off the stone
      return s.lead
        ? at(x0, top + i * leading, 0, i === 0 ? 0.92 : s.measure, i === 0 ? 2.5 : 1)
        : at(stackX, stackY + 16, s.tilt, ...chit)
  }
}

function PressFloor({ stage }) {
  const ref = useRef(null)
  const [box, setBox] = useState({ w: 0, h: 0 })

  // Measured, because translateX(%) resolves against the slip's own 240px and
  // the forme has to centre on the band. useLayoutEffect so the first paint
  // already has the real width.
  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const read = () => setBox({ w: el.clientWidth, h: el.clientHeight })
    read()
    const ro = new ResizeObserver(read)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  const { w, h } = box
  const x0 = (w - SLIP_W) / 2
  const ruleY = (h - LEADS * 12) / 2 - 8 // sits above the first line of the forme
  const formed = stage === STAGES.length - 1

  return (
    <div ref={ref} className="press-floor" aria-hidden="true">
      {/* The masthead rule, drawn only once the page exists. */}
      <hr
        className="rule-double press-forme-rule"
        style={{
          width: `${SLIP_W}px`,
          transform: `translate(${x0.toFixed(1)}px, ${ruleY.toFixed(1)}px) scaleX(${formed ? 1 : 0})`,
          opacity: formed ? 1 : 0,
        }}
      />
      {w > 0 &&
        SLIPS.map((s, i) => (
          <span
            key={i}
            className="press-slip"
            // From the moment the stacks form, the lead of each one darkens
            // and sits on top of its duplicates. That is the slip that will
            // still be there at the end.
            data-lead={stage >= 2 && s.lead ? '1' : undefined}
            data-run={formed && s.lead ? '1' : undefined}
            style={{
              zIndex: s.lead ? 2 : 1,
              transform: slipTransform(s, i, stage, w, h),
              opacity: formed && !s.lead ? 0 : 1,
              transitionDelay: `${Math.min(i * 12, 420)}ms`,
            }}
          />
        ))}
    </div>
  )
}

function ThePress() {
  const wrapRef = useRef(null)
  const [stage, setStage] = useState(0)

  useEffect(() => {
    if (REDUCED) return setStage(STAGES.length - 1)
    const onScroll = () => {
      const el = wrapRef.current
      if (!el) return
      const r = el.getBoundingClientRect()
      const span = r.height - innerHeight
      if (span <= 0) return
      const p = Math.min(1, Math.max(0, -r.top / span))
      setStage(Math.min(STAGES.length - 1, Math.floor(p * STAGES.length)))
    }
    onScroll()
    addEventListener('scroll', onScroll, { passive: true })
    return () => removeEventListener('scroll', onScroll)
  }, [])

  const [n, label, note] = STAGES[stage]

  return (
    <section ref={wrapRef} className="pad-x relative" style={{ height: '340vh' }}>
      <div className="press-stage mx-auto max-w-[1140px]">
        <p className="label-rule eyebrow">The overnight run</p>
        <div className="mt-10 flex flex-wrap items-center gap-x-14 gap-y-10">
          <div className="min-w-0 flex-[1_1_18rem]">
            <p
              key={n}
              className="display impress text-[clamp(64px,13vw,150px)] leading-[0.92] text-[var(--oxide)] tabular-nums"
            >
              {n}
            </p>
            <p className="eyebrow mt-2">{label}</p>
            <p className="mt-5 max-w-[34ch] text-[16px] leading-[1.6] text-[var(--ink-soft)]">
              {note}
            </p>
          </div>

          {/* The funnel, drawn as bars that contract at each stage. */}
          <div className="flex min-w-0 flex-[1_1_22rem] flex-col justify-center gap-2.5">
            {STAGES.map((_, i) => (
              <div key={i} className="flex items-center gap-4">
                <span className="eyebrow w-12 shrink-0">{STAGES[i][0]}</span>
                <span className="h-[10px] flex-1" style={{ background: 'var(--rule-faint)' }}>
                  <span
                    className="block h-full transition-[width,opacity] duration-700 ease-out"
                    style={{
                      width: i <= stage ? `${100 / (i * 1.9 + 1)}%` : '0%',
                      opacity: i <= stage ? 1 : 0,
                      background: i === stage ? 'var(--oxide)' : 'var(--rule)',
                    }}
                  />
                </span>
              </div>
            ))}
            <p className="eyebrow mt-5">
              Stage {stage + 1} of {STAGES.length} &middot; scroll to run the night
            </p>
          </div>
        </div>

        <PressFloor stage={stage} />
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------- Norm
   SPEC 14.8: an opt-in agent that answers on the reader's own stories and
   tracks how coverage of a story develops. A side branch, never part of
   assembling or delivering the newsletter.

   The mug, its steam, the thinking phrases and the exchanges are the
   prototype's, verbatim. The coverage chart is designed from the spec, since
   the tracker has no UI anywhere: decision #40 names charting coverage over
   time and a server-side scheduler as the reason the platform was chosen.

   Not here, deliberately: any past-chats list or saved-thread affordance.
   Decision #54 defers it and #41 forbids storing agent output, so the section
   stays silent on persistence rather than implying it. */

const THINK = [
  'Norm is pulling the archive…',
  'Norm is checking his notes…',
  'Norm is re-reading 56 editions…',
  'Norm is refilling the mug…',
]

const EXCHANGES = [
  {
    q: 'How far have AI-run attacks actually got?',
    a: "Two data points this week: Anthropic's models broke out of a test and reached three real companies, and a hacker let DeepSeek run server attacks with almost no input.",
    cite: '3 editions · 7 sources',
  },
  {
    q: 'Did either actually break in?',
    a: 'Mostly no — most of the DeepSeek targets held. The shift is in how little the human had to do. No. 055 has the Unit 42 detail.',
    cite: '1 edition · 2 sources',
  },
  {
    q: 'Why is Congress asking DoorDash about Kimi?',
    a: "Because US firms are picking up cheaper Chinese models. Lawmakers want DoorDash's AI, security and procurement people to brief them by August 21.",
    cite: '2 editions · 5 sources',
  },
]

/* The mark, and the thinking indicator. Paths and keyframe timings are the
   prototype's; only the gradient id is namespaced to avoid a collision. */
function Mug({ size = 26, thinking = false }) {
  return (
    <svg
      viewBox="16 2 96 106"
      aria-hidden="true"
      style={{ width: (size * 24) / 26, height: size, display: 'block', flex: 'none' }}
      className="norm-mug"
      data-thinking={thinking}
    >
      <defs>
        <linearGradient id="norm-steam" gradientUnits="userSpaceOnUse" x1="0" y1="52" x2="0" y2="4">
          <stop offset="0" stopColor="currentColor" stopOpacity="1" />
          <stop offset=".4" stopColor="currentColor" stopOpacity=".8" />
          <stop offset=".72" stopColor="currentColor" stopOpacity=".3" />
          <stop offset="1" stopColor="currentColor" stopOpacity="0" />
        </linearGradient>
      </defs>
      <g fill="none" stroke="url(#norm-steam)" strokeWidth="6" strokeLinecap="round" className="norm-steam">
        <path d="M56,52 C44,42 68,34 54,22 C46,14 62,9 57,1" strokeDasharray="30 14" className="norm-curl" />
        <path d="M74,50 C82,42 70,36 76,28" strokeWidth="4" className="norm-breathe-a" />
        <path d="M39,50 C32,43 43,37 38,30" strokeWidth="4" className="norm-breathe-b" />
      </g>
      <path d="M84,68 C102,68 102,90 84,90" fill="none" stroke="currentColor" strokeWidth="8" strokeLinecap="round" />
      <rect x="28" y="58" width="56" height="42" rx="6" ry="6" fill="currentColor" />
    </svg>
  )
}

/* One orchestrated loop rather than scattered effects:
   question -> thinking -> answer -> citation -> hold -> next. */
const PHASES = [
  { name: 'ask', ms: 900 },
  { name: 'think', ms: 1900 },
  { name: 'answer', ms: 1300 },
  { name: 'hold', ms: 2400 },
]

function Conversation() {
  const [i, setI] = useState(0)
  const [phase, setPhase] = useState(REDUCED ? 3 : 0)
  const [think, setThink] = useState(0)

  useEffect(() => {
    if (REDUCED) return
    const t = setTimeout(() => {
      if (phase < PHASES.length - 1) setPhase(phase + 1)
      else {
        setPhase(0)
        setI((n) => (n + 1) % EXCHANGES.length)
      }
    }, PHASES[phase].ms)
    return () => clearTimeout(t)
  }, [phase])

  useEffect(() => {
    if (REDUCED || PHASES[phase].name !== 'think') return
    const t = setInterval(() => setThink((n) => (n + 1) % THINK.length), 700)
    return () => clearInterval(t)
  }, [phase])

  const ex = EXCHANGES[i]
  const p = PHASES[phase].name
  const showAnswer = p === 'answer' || p === 'hold'

  return (
    <div className="sheet px-6 py-6 sm:px-7">
      <p className="eyebrow flex items-center justify-between">
        <span>Ask Norm</span>
        <span className="eyebrow-oxide">On your editions</span>
      </p>
      <hr className="mt-3 border-0 border-t" style={{ borderColor: 'var(--ink)' }} />

      {/* The loop is decorative; the readable copy is the static list below. */}
      <div className="norm-stage" aria-hidden="true">
        <p key={`q${i}`} className="norm-q">
          {ex.q}
        </p>

        {p === 'think' && (
          <div className="norm-think">
            <Mug size={26} thinking />
            <span className="flex min-w-0 flex-col gap-[5px]">
              <span className="norm-thinktext">{THINK[think]}</span>
              <span className="norm-thinkrule" />
            </span>
          </div>
        )}

        {showAnswer && (
          <div key={`a${i}`} className="norm-answer">
            <p className="norm-a">{ex.a}</p>
            <p className="norm-cite">{ex.cite}</p>
          </div>
        )}
      </div>

      <div className="norm-composer">
        <span className="norm-composer-input">Ask about a story or an edition</span>
        <span className="norm-composer-btn">Ask</span>
      </div>

      <ul className="sr-only">
        {EXCHANGES.map((e) => (
          <li key={e.q}>
            Question: {e.q} Answer: {e.a} Drawn from {e.cite}.
          </li>
        ))}
      </ul>
    </div>
  )
}

const NORM_POINTS = [
  [
    'It only ever sees your paper',
    'Every lookup is scoped to one reader on the server, and the sandbox it runs in holds no database credentials at all.',
  ],
  [
    'Every answer shows its work',
    'Which editions it read and how many sources were behind them, on the answer itself, so you can go and check.',
  ],
]

function NormAgent() {
  return (
    <section id="norm" className="pad-x py-20">
      <div className="mx-auto max-w-[1140px]">
        <Reveal>
          <p className="label-rule eyebrow">Ask the paper</p>
        </Reveal>

        <div className="mt-12 flex flex-wrap items-start gap-x-16 gap-y-12">
          <Reveal delay={80} className="min-w-0 flex-[1_1_23rem]">
            <div className="flex items-center gap-3">
              <span className="text-[var(--oxide)]">
                <Mug size={34} />
              </span>
              <h2 className="display text-[clamp(30px,4.6vw,50px)]">Norm read all of it.</h2>
            </div>
            <p className="mt-5 max-w-[46ch] text-[16px] leading-[1.62] text-[var(--ink-soft)]">
              Every edition you have been sent is still there, and Norm can be asked about any of
              it. Not the whole internet. Your paper, and the sources it was set from.
            </p>

            <ul className="mt-10 border-t" style={{ borderColor: 'var(--rule)' }}>
              {NORM_POINTS.map(([head, body]) => (
                <li key={head} className="border-b py-4" style={{ borderColor: 'var(--rule-faint)' }}>
                  <p className="font-display text-[19px] font-medium">{head}</p>
                  <p className="mt-1.5 max-w-[44ch] text-[14.5px] leading-[1.6] text-[var(--muted)]">
                    {body}
                  </p>
                </li>
              ))}
            </ul>

            <p className="eyebrow mt-6">Opt in when you want it &middot; off until you do</p>
          </Reveal>

          <Reveal delay={160} className="min-w-0 flex-[1_1_23rem]">
            <Conversation />
          </Reveal>
        </div>
      </div>
    </section>
  )
}

/* -------------------------------------- closing statement + the single CTA */

function Build() {
  const [email, setEmail] = useState('')
  const [done, setDone] = useState(false)

  return (
    <section id="build" className="pad-x py-24">
      <div className="mx-auto max-w-[1140px]">
        <Reveal>
          <p className="label-rule eyebrow">Coming soon</p>
          <h2 className="display mt-8 max-w-[17ch] text-[clamp(32px,5.2vw,58px)]">
            Tomorrow&rsquo;s news engine is currently being built.
          </h2>
          <p className="mt-5 max-w-[48ch] text-[17px] leading-[1.6] text-[var(--ink-soft)]">
            We are meticulously engineering a smarter, quieter way to read the news. Leave your
            email below to trace our progress, receive behind-the-scenes engineering updates, and
            secure priority early access the moment the first public edition drops.
          </p>
        </Reveal>

        <Reveal delay={100}>
          <form
            className="mt-10 max-w-[520px]"
            onSubmit={(e) => {
              e.preventDefault()
              setDone(true)
            }}
          >
            {done ? (
              <p className="display text-[24px] text-[var(--oxide)]">
                You are on the list. We will write when there is something to show.
              </p>
            ) : (
              <>
                <label htmlFor="email" className="eyebrow">
                  Where should we reach you
                </label>
                <div className="mt-2 flex flex-col gap-4 sm:flex-row sm:items-end">
                  <input
                    id="email"
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@example.com"
                    className="field flex-1"
                  />
                  <button type="submit" className="btn-oxide px-8 py-3.5 text-[15px]">
                    Secure Early Access
                  </button>
                </div>
                {/* Set in the eyebrow's own uppercase, like the tag and the
                    label above it. The old line carried normal-case. */}
                <p className="eyebrow mt-4">
                  One address. Zero noise. We will only email you with major milestones and system
                  release dates.
                </p>
              </>
            )}
          </form>
        </Reveal>
      </div>
    </section>
  )
}

function Footer() {
  return (
    <footer className="pad-x pb-16">
      <div className="mx-auto max-w-[1140px]">
        <hr className="rule-double" />
        <div className="flex flex-wrap items-end justify-between gap-6 pt-6">
          <p className="display text-[22px]">Norm&rsquo;s Newsletter</p>
          <p className="eyebrow">Est. 2025 &middot; set nightly at 6:00 am ET</p>
        </div>
      </div>
    </footer>
  )
}

/* -------------------------------------------------------------------- app */

export default function App() {
  const [idx, setIdx] = useState(1)
  const tod = STOPS[idx][1]

  // The palette has to live on :root, or body keeps the default background
  // while its children re-light and the page splits in two.
  useEffect(() => {
    document.documentElement.dataset.tod = tod
  }, [tod])

  // The pointer position feeds the CTA's ink bloom.
  useEffect(() => {
    const move = (e) => {
      const b = e.target.closest?.('.btn-oxide')
      if (!b) return
      const r = b.getBoundingClientRect()
      b.style.setProperty('--mx', `${((e.clientX - r.left) / r.width) * 100}%`)
      b.style.setProperty('--my', `${((e.clientY - r.top) / r.height) * 100}%`)
    }
    addEventListener('pointermove', move)
    return () => removeEventListener('pointermove', move)
  }, [])

  return (
    <div className="tod">
      <Masthead />
      <main>
        <Hero />
        <Benefits />
        <TopicStudio />
        <Reinforce />
        <DeliveryDial idx={idx} setIdx={setIdx} />
        <ThePress />
        <NormAgent />
        <Build />
      </main>
      <Footer />
    </div>
  )
}
